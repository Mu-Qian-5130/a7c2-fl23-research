"""Read capacity from local firmware images. No mounts or camera operations."""
from pathlib import Path
import struct


def inspect(image):
    image=Path(image)
    with image.open('rb') as stream:
        head=stream.read(2048)
        if head[1080:1082]==b'\x53\xef':
            sb=head[1024:]
            inodes,blocks,reserved,free_blocks,free_inodes,first,shift=struct.unpack_from('<7I',sb)
            block=1024<<shift
            return dict(filesystem='ext2',image_bytes=image.stat().st_size,block_bytes=block,
                total_bytes=blocks*block,free_bytes=free_blocks*block,
                unreserved_free_bytes=max(0,free_blocks-reserved)*block,
                inodes=inodes,free_inodes=free_inodes)
        if head[54:59]==b'FAT12':
            sector=struct.unpack_from('<H',head,11)[0];per_cluster=head[13]
            reserved=struct.unpack_from('<H',head,14)[0];fats=head[16]
            entries=struct.unpack_from('<H',head,17)[0]
            sectors=struct.unpack_from('<H',head,19)[0] or struct.unpack_from('<I',head,32)[0]
            fat_sectors=struct.unpack_from('<H',head,22)[0]
            root_sectors=(entries*32+sector-1)//sector
            count=(sectors-reserved-fats*fat_sectors-root_sectors)//per_cluster
            stream.seek(reserved*sector);fat=stream.read(fat_sectors*sector)
            def entry(cluster):
                at=cluster*3//2;word=int.from_bytes(fat[at:at+2],'little')
                return (word>>4 if cluster&1 else word)&0xfff
            free=sum(entry(n)==0 for n in range(2,count+2));cluster=sector*per_cluster
            return dict(filesystem='FAT12',image_bytes=image.stat().st_size,block_bytes=cluster,
                total_bytes=count*cluster,free_bytes=free*cluster,unreserved_free_bytes=free*cluster,
                clusters=count,free_clusters=free)
    raise ValueError('Unsupported local filesystem capacity report: '+image.name)


def report(originals,edited,files):
    rows={}
    for role,changes in files.items():
        before=inspect(Path(originals)/(role+'.img'));after=inspect(edited[role])
        if (before['image_bytes'],before['total_bytes'])!=(after['image_bytes'],after['total_bytes']):
            raise ValueError('Firmware filesystem geometry changed: '+role)
        rows[role]=dict(before=before,after=after,
            free_bytes_change=after['free_bytes']-before['free_bytes'],
            added_or_replaced_bytes=sum(Path(row['source']).stat().st_size for row in changes.values() if not row.get('delete')),
            deleted_files=sum(bool(row.get('delete')) for row in changes.values()))
    return dict(camera_io=False,physical_free_space_measured=False,scope='local-filesystem-images',partitions=rows)
