/* Wi-Fi events start/stop SSH. Blocking netlink receive; no polling/timers. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <linux/netlink.h>
#include <linux/rtnetlink.h>
#include <net/if.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#ifndef SERVICE_ROOT
#define SERVICE_ROOT "/usr/lib/a7c2-tools/ssh"
#endif
#ifndef STATE_ROOT
#define STATE_ROOT "/tmp_wbshd"
#endif
#ifndef BUSYBOX
#define BUSYBOX "/bin/busybox"
#endif
static volatile sig_atomic_t quitting,network_fd=-1;
static void stop_signal(int sig){(void)sig;quitting=1;if(network_fd>=0){close(network_fd);network_fd=-1;}}
static void wifi_address(char *out,size_t size) {
    struct ifaddrs *all=NULL;out[0]=0;if(getifaddrs(&all))return;
    for(struct ifaddrs *a=all;a;a=a->ifa_next) {
        if(!a->ifa_addr||a->ifa_addr->sa_family!=AF_INET)continue;
        if(!(a->ifa_flags&IFF_UP)||!(a->ifa_flags&IFF_RUNNING))continue;
        char path[128];snprintf(path,sizeof(path),"/sys/class/net/%s/wireless",a->ifa_name);struct stat st;
        if(stat(path,&st)&&strncmp(a->ifa_name,"wlan",4)&&strncmp(a->ifa_name,"p2p",3))continue;
        struct sockaddr_in *address=(struct sockaddr_in*)a->ifa_addr;
        if(address->sin_addr.s_addr&&inet_ntop(AF_INET,&address->sin_addr,out,size))break;
    }
    freeifaddrs(all);
}
static void stop_service(pid_t *child) {
    if(*child<=0)return;
    kill(-*child,SIGTERM);while(waitpid(*child,NULL,0)<0&&errno==EINTR){}*child=0;
}
int main(void) {
    int lock=open(STATE_ROOT "/a7c2-wifi-ssh.lock",O_CREAT|O_RDWR,0600);
    if(lock<0||flock(lock,LOCK_EX|LOCK_NB))return 1;fcntl(lock,F_SETFD,FD_CLOEXEC);
    int fd=socket(AF_NETLINK,SOCK_RAW|SOCK_CLOEXEC,NETLINK_ROUTE);
    struct sockaddr_nl address={.nl_family=AF_NETLINK,.nl_groups=RTMGRP_LINK|RTMGRP_IPV4_IFADDR};
    if(fd<0||bind(fd,(struct sockaddr*)&address,sizeof(address)))return 2;
    network_fd=fd;
    struct sigaction action={.sa_handler=stop_signal};sigemptyset(&action.sa_mask);
    sigaction(SIGTERM,&action,NULL);sigaction(SIGINT,&action,NULL);
    pid_t child=0;char active[INET_ADDRSTRLEN]={0};
    while(!quitting) {
        char ready[INET_ADDRSTRLEN];wifi_address(ready,sizeof(ready));
        if(strcmp(ready,active)) {
            stop_service(&child);snprintf(active,sizeof(active),"%s",ready);
            if(active[0]) {
                sigset_t blocked,previous;sigemptyset(&blocked);sigaddset(&blocked,SIGTERM);sigaddset(&blocked,SIGINT);
                sigprocmask(SIG_BLOCK,&blocked,&previous);
                child=fork();
                if(!child){
                    signal(SIGTERM,SIG_DFL);signal(SIGINT,SIG_DFL);setpgid(0,0);close(fd);close(lock);
                    sigprocmask(SIG_SETMASK,&previous,NULL);
                    execl(BUSYBOX,"busybox","sh",SERVICE_ROOT "/boot.sh",active,(char*)0);_exit(127);
                }
                if(child>0)setpgid(child,child);
                sigprocmask(SIG_SETMASK,&previous,NULL);
            }
        }
        char messages[8192];ssize_t n=recv(fd,messages,sizeof(messages),0);
        if(n<0&&errno!=EINTR&&errno!=ENOBUFS)break;
        if(child>0&&waitpid(child,NULL,WNOHANG)==child)child=0;
    }
    stop_service(&child);if(network_fd>=0)close(fd);close(lock);return 0;
}
