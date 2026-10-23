"""Parse bounded context journals; a file alone NEVER grants process cleanup."""
import struct

SIZE=352
ACTIONS=(79,56,80,0x80000010,222,0x8000000a,0x8000000b,215,57)


def context(raw):
    v=struct.unpack_from('<12I8q5Q4Iq',raw)
    p=struct.unpack_from('<10I3qQ',raw,176)
    return dict(magic=v[0],version=v[1],phase=v[2],ownership=v[3],nonce=v[4],
                syscalls=[v[i] for i in (5,6,7,8,9,10)],status=v[29],
                descriptor=v[12],native_statuses=list(v[13:20]),
                shared_begin=v[23],shared_bytes=v[24],info=list(v[25:29]),
                probe=dict(magic=p[0],version=p[1],phase=p[2],ownership=p[3],mode=p[4],nonce=p[5],
                           allocation=p[6],send=p[7],release=p[8],
                           allocation_status=p[10],release_status=p[12],message=p[13]))


def records(raw,nonce):
    if not raw or len(raw)%SIZE or len(raw)>32*SIZE:
        raise ValueError('Empty/truncated/oversized journal')
    rows=[]
    for at in range(0,len(raw),SIZE):
        h=struct.unpack_from('<8s12I4Q2q',raw,at)
        if h[:4]!=(b'IPCCAN01',1,SIZE,nonce) or h[4]!=len(rows)+1 or h[12]:
            raise ValueError('Journal identity/sequence/reserved mismatch')
        if h[5] not in (0,1,2,3) or h[6] not in (0,1) or h[7] not in (0,1):
            raise ValueError('Journal state invalid')
        if not 0<h[13]<=0x7fffffff or not 0<h[14]<=0x7fffffff or (h[6] and h[15]):
            raise ValueError('Invalid process/effective UID')
        rows.append(dict(sequence=h[4],edge=h[5],returned=h[6],waiting=h[7],syscalls=h[8],ioctls=h[9],
                         closed_inherited=h[10],live_fds=h[11],pid=h[13],parent=h[14],euid=h[15],action=h[16],
                         action_result=h[17],status=h[18],context=context(raw[at+104:at+SIZE])))
    return rows


def decode(raw,nonce):
    rows=records(raw,nonce)
    first=rows[0]
    if first['edge']!=0 or first['action'] or first['action_result'] or first['returned'] or first['waiting']:
        raise ValueError('Missing fresh START')
    if any(raw[104:SIZE]) or first['syscalls'] or first['ioctls']:
        raise ValueError('START contains used context')
    pending=None;syscalls=ioctls=0;operations=[]
    identity=tuple(first[key] for key in ('pid','parent','euid','closed_inherited','live_fds'))
    for index,row in enumerate(rows[1:],1):
        if tuple(row[key] for key in ('pid','parent','euid','closed_inherited','live_fds'))!=identity:
            raise ValueError('Process/setup identity changed')
        if row['context']['probe']['send']:
            raise ValueError('Journal cannot admit any send')
        if row['edge'] in (1,2) or row['returned']:
            c=row['context']
            if c['magic']!=0x58544349 or c['version']!=1 or c['nonce']!=nonce:
                raise ValueError('Context identity changed')
        if row['edge']==1:
            if pending is not None or row['action'] not in ACTIONS or row['action_result']!=-1:
                raise ValueError('Repeated/unsupported native action')
            if row['returned'] or row['waiting']:raise ValueError('Native action after final state')
            if row['action']<0x80000000:syscalls+=1
            else:ioctls+=1
            if syscalls>6 or ioctls>3:raise ValueError('Native call bound exceeded')
            pending=row['action'];operations.append(pending)
        elif row['edge']==2:
            if pending!=row['action']:raise ValueError('Unmatched AFTER')
            if row['returned'] or row['waiting']:raise ValueError('AFTER has final state')
            pending=None
        elif row['edge']==3:
            if pending is not None or index!=len(rows)-1 or row['action'] or row['action_result']!=row['status']:
                raise ValueError('Incomplete/repeated FINAL')
            if bool(row['waiting'])!=(row['context']['ownership']!=0):
                raise ValueError('Ownership contradicts wait state')
        else:raise ValueError('Repeated START')
        if (row['syscalls'],row['ioctls'])!=(syscalls,ioctls):
            raise ValueError('Action counters differ')
    last=rows[-1]
    success=last['edge']==3 and last['returned']==1 and last['status']==0 and last['waiting']==0
    if success:
        c=last['context'];p=c['probe']
        if operations!=list(ACTIONS) or len(rows)!=20 or first['status'] or first['euid'] or first['live_fds']!=2:
            raise ValueError('Success lacks exact never-sent sequence')
        if not (c['magic']==0x58544349 and c['version']==1 and c['nonce']==nonce and
                c['phase']==9 and c['ownership']==c['status']==0 and c['syscalls']==[2,1,1,1,1,1] and
                p['magic']==0x31514f50 and p['version']==1 and p['nonce']==nonce and p['mode']==0 and
                p['phase']==6 and p['ownership']==0 and p['allocation']==p['release']==1 and
                p['send']==p['allocation_status']==p['release_status']==0):
            raise ValueError('Success lacks resolved context/probe')
        start,size=c['shared_begin'],c['shared_bytes']
        if not (0<=c['descriptor']<=0x7fffffff and start>=4096 and not start&4095 and
                size==0x200000 and start+size<1<<64 and not p['message']&63 and
                start+64<=p['message']<=start+size-20 and c['info'][:3]==[size,0x80000,0x20000]):
            raise ValueError('Success lacks bounded native mapping/allocation')
        wanted=[0,c['descriptor'],0,0,start,0,0,0,0]
        if [row['action_result'] for row in rows if row['edge']==2]!=wanted:
            raise ValueError('Success includes mismatched native return')
        if c['native_statuses']!=[0,c['descriptor'],0,0,start,0,0]:
            raise ValueError('Final native statuses differ from journal')
    return dict(records=len(rows),success_record=success,has_final_record=last['edge']==3,
                waiting=last['waiting'],last=last,native_actions=operations,
                cleanup_allowed=False,process_observation_required=True)
