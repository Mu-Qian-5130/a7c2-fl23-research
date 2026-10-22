"""Direction-aware selection inside the existing native gauge update function.

No new code segment, allocated stub, redirected call or stack-layout change.
X23 keeps the existing shared row across calls; X24 keeps the layout pointer
only after its former maximum-value use. Both are callee-saved by AAPCS64.
"""
OFFSET=0x17e28a4
BEFORE=bytes.fromhex('0050179b1540a07202e04029651047290003024ba5130d290100621ec002024b65904829a5930e29240280520440a0720018611e0100621e60184629634001910200621e60005fb82108401f0200621e601242b90000024b2128631e2100781e0100621e0008411fa11b0c2961c05fb8a17f00b9410280520140a0720028631e0000781ea07300b9607648391f000071a00280520040a0728410811ab512801a5f00166be2a79f1ae00313aaa100805287ffff97638e69f91f03166be2d79f1ae403152ae00313aa63800191c10080527fffff97600a82b922008052638e69f94100805263800091007c179b846a60b8e00313aab4030191a4feff97638e69f9e00313aa247884522200805263c001910440a072e10080529cfeff97638e69f9e00313aa4478845222008052630002910440a0720101805294feff97')
AFTER=bytes.fromhex('1750179b1540a072e2e24029651047290003024ba5130d290100621ec002024b65904829a5930e29240280520440a0720018611e0100621e60184629634001910200621e60005fb82108401f0200621e601242b90000024b2128631e2100781e0100621e0008411fa11b0c2961c05fb8a17f00b9410280520140a0720028631e0000781ea07300b9607648391f000071a00280520040a0728410811ab512801a5f00166be2a79f1ae00313aaa100805287ffff971f03166b788e69f9e2d79f1ae403152ae00313aa03830191c10080527fffff97e40240b969d641b93f01007189340d53e903891a8428092a220080520383009141008052e00313aab4030191a2feff97e00313aa247884522200805203c301910440a072e10080529bfeff97e00313aa4478845222008052030302910440a0720101805294feff97')


def window(ap):
    current=ap[OFFSET:OFFSET+len(BEFORE)]
    if len(current)!=len(BEFORE) or any(c not in (a,b) for c,a,b in zip(current,BEFORE,AFTER)):
        raise ValueError('Native gauge instructions differ at '+hex(OFFSET))
    return dict(offset=OFFSET,before_hex=BEFORE.hex(),after_hex=AFTER.hex(),label='portrait_gauge_selection')


def horizontal_active(ap):
    current=ap[OFFSET:OFFSET+len(BEFORE)]
    return len(current)==len(BEFORE) and current!=BEFORE and all(c in (a,b) for c,a,b in zip(current,BEFORE,AFTER))

# Creative Look uses the native vertical-control class. Its cached portrait
# flag already drives horizontal geometry, but its image table stays shared.
VERTICAL_OFFSET=0x17e3490
VERTICAL_BEFORE=bytes.fromhex('60fa41b961da41b9a05300b960fe41b9bf7f03a9a13300b9a05700b961f240f9600242b9a11f00f9a05b00b961f640f960124839f51300f975c20f91a12300f9a1c30091a0730139e00315aaf9b6ff97600a82b9810180d2007c019bc1fb00f021e00991206860b8602e04b9')
VERTICAL_AFTER=bytes.fromhex('60fe40f961da41b9a02b00f9bf7f03a9a13300b961f240f9600242b9a11f00f9a05b00b961f640f960124839f51300f975c20f91a12300f9a1c30091a0730139e00315aafbb6ff97600a82b9810180d2007c019bc1fb00f021e00991206860b861f2703920001433602e04b9')

def windows(ap):
    result=[window(ap)]
    current=ap[VERTICAL_OFFSET:VERTICAL_OFFSET+len(VERTICAL_BEFORE)]
    if len(current)!=len(VERTICAL_BEFORE) or any(c not in (a,b) for c,a,b in zip(current,VERTICAL_BEFORE,VERTICAL_AFTER)):
        raise ValueError("Native Creative Look gauge instructions differ at "+hex(VERTICAL_OFFSET))
    result.append(dict(offset=VERTICAL_OFFSET,before_hex=VERTICAL_BEFORE.hex(),after_hex=VERTICAL_AFTER.hex(),label="portrait_creative_look_gauge"))
    return result

def active(ap):
    current=ap[VERTICAL_OFFSET:VERTICAL_OFFSET+len(VERTICAL_BEFORE)]
    return horizontal_active(ap) or (len(current)==len(VERTICAL_BEFORE) and current!=VERTICAL_BEFORE and all(c in (a,b) for c,a,b in zip(current,VERTICAL_BEFORE,VERTICAL_AFTER)))
