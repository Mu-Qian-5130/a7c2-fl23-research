local LrExportSession = import 'LrExportSession'
local LrFileUtils = import 'LrFileUtils'
local LrTasks = import 'LrTasks'
local Verification = {}

local function unescape(value)
    return (value:gsub('&quot;', '"'):gsub('&apos;', "'"):gsub('&lt;', '<'):gsub('&gt;', '>'):gsub('&amp;', '&'))
end

function Verification.exportedProfile(path)
    local file=assert(io.open(path,'rb'))
    local bytes=file:read('*a');file:close()
    if bytes:sub(1,2)~='\255\216' then return nil end
    local at=3;local xmp=nil
    local header='http://ns.adobe.com/xap/1.0/\0'
    while at+3<=#bytes do
        local prefix,marker=bytes:byte(at,at+1)
        if prefix~=255 or marker==218 or marker==217 then break end
        local high,low=bytes:byte(at+2,at+3);local length=high*256+low
        if length<2 or at+1+length>#bytes then break end
        local data=bytes:sub(at+4,at+1+length)
        if marker==225 and data:sub(1,#header)==header then xmp=data:sub(#header+1);break end
        at=at+2+length
    end
    if not xmp then return nil end
    local name=xmp:match('crs:CameraProfile="([^"]+)"')
        or xmp:match("crs:CameraProfile='([^']+)'")
        or xmp:match('<crs:CameraProfile>(.-)</crs:CameraProfile>')
    return name and unescape(name)
end

local function render(photo, folder)
    LrFileUtils.createAllDirectories(folder)
    local session=LrExportSession {
        photosToExport={ photo },
        exportSettings={
            LR_export_destinationType='specificFolder', LR_export_destinationPathPrefix=folder,
            LR_export_useSubfolder=false, LR_format='JPEG', LR_export_colorSpace='sRGB',
            LR_jpeg_quality=.6, LR_collisionHandling='overwrite', LR_size_doConstrain=true,
            LR_size_maxWidth=320, LR_size_maxHeight=320, LR_size_resizeType='longEdge',
            LR_minimizeEmbeddedMetadata=false, LR_removeLocationMetadata=true,
        },
    }
    for _,rendition in session:renditions({ stopIfCanceled=true }) do
        local success,path=rendition:waitForRender()
        if not success then error(tostring(path)) end
        local actual=Verification.exportedProfile(path)
        LrFileUtils.delete(path)
        return actual
    end
    error('No A7Look profile verification rendition was produced')
end

function Verification.render(photo, folder)
    local ok,actual=LrTasks.pcall(function() return render(photo,folder) end)
    if not ok then return nil,tostring(actual) end
    return actual
end

return Verification
