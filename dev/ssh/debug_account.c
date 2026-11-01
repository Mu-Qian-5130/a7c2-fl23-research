/* Process-local account view for this independent public-key-only debug server.
 * Sony's original root shell is /bin/false. Do not edit /etc/passwd, PAM or the
 * native SSH manager. Link this object only into the private Dropbear build.
 */
#include <pwd.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

static struct passwd debug_root={
    .pw_name="root",.pw_passwd="x",.pw_uid=0,.pw_gid=0,
    .pw_gecos="A7C2 temporary SSH",.pw_dir="/",.pw_shell="/bin/sh"
};

struct passwd *a7c2_debug_getpwnam(const char *name) {
    return geteuid()==0&&name&&strcmp(name,"root")==0?&debug_root:0;
}

struct passwd *a7c2_debug_getpwuid(uid_t uid) {
    return geteuid()==0&&uid==0?&debug_root:0;
}
