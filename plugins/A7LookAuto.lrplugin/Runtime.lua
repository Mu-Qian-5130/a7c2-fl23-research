local LrApplication = import 'LrApplication'
local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'
local LrTasks = import 'LrTasks'
local LrDate = import 'LrDate'
local Config = require 'Config'
local Logic = require 'Logic'
local Verification = require 'Verification'
local Queue = require 'Queue'
local Runtime = {}

local function write(path, value)
    local file = assert(io.open(path, 'w')); file:write(value); file:close()
end
local function hex(value) return (value:gsub('.', function(c) return string.format('%02x', c:byte()) end)) end
local function unhex(value) return (value:gsub('..', function(c) return string.char(tonumber(c,16)) end)) end
local function log(message)
    local file=io.open(Config.log,'a')
    if file then file:write(os.date('%Y-%m-%d %H:%M:%S')..' '..message..'\n');file:close() end
end
local function shell(value)
    if WIN_ENV then return '"'..value:gsub('"','')..'"' end
    return "'"..value:gsub("'","'\\''").."'"
end

function Runtime.start(context)
    if _G.A7LookAuto and _G.A7LookAuto.running then return end
    local state={ running=true, seen={}, pending={}, blocked={}, applied=0, skipped=0, sequence=0 }
    _G.A7LookAuto=state
    context:addCleanupHandler(function() state.running=false end)
    LrFileUtils.createAllDirectories(Config.work_root)
    local queuePath=LrPathUtils.child(Config.work_root,'pending-imports.tsv')
    local catalogPath=nil
    local retained={}
    local function savePending()
        local rows={}
        for _,row in ipairs(retained) do rows[#rows+1]=row end
        for _,items in ipairs({state.pending,state.blocked}) do
            for id,item in pairs(items) do
                rows[#rows+1]={catalog=catalogPath,id=id,path=item.path,profile=item.profile}
            end
        end
        Queue.write(queuePath,rows)
    end
    while state.running do
        local ok,err=LrTasks.pcall(function()
            local catalog=LrApplication.activeCatalog()
            local path=catalog:getPath()
            local photos=catalog:getAllPhotos()
            local now=LrDate.currentTime()
            if catalogPath~=path then
                local previous=Queue.read(queuePath)
                catalogPath=path;state.seen={};state.pending={};state.blocked={};retained={}
                local index={}
                for _,photo in ipairs(photos) do
                    local id=tostring(photo.localIdentifier)
                    state.seen[id]=true;index[id]=photo
                end
                for _,row in ipairs(previous) do
                    if row.catalog==path then
                        local photo=index[row.id]
                        if photo and photo:getRawMetadata('path')==row.path then
                            state.pending[row.id]={photo=photo,path=row.path,profile=row.profile,firstSeen=now-3}
                        end
                    else retained[#retained+1]=row end
                end
                state.status='Watching new imports; existing photos retained'
                write(Config.status,Config.install_id..'\nREADY\n'..tostring(#photos)..'\n')
                log('READY '..Config.install_id..' baseline='..tostring(#photos))
            else
                local added=false
                for _,photo in ipairs(photos) do
                    local id=tostring(photo.localIdentifier)
                    if not state.seen[id] then
                        state.seen[id]=true
                        local file=photo:getRawMetadata('path')
                        if file and file:lower():match('%.arw$') then
                            added=true
                            state.pending[id]={ photo=photo, path=file, firstSeen=now,
                                profile=photo:getDevelopSettings().CameraProfile }
                        end
                    end
                end
                if added then savePending() end
                local selected={};local lines={}
                for id,item in pairs(state.pending) do
                    if now-item.firstSeen>=3 and #lines<32 then
                        selected[id]=item;lines[#lines+1]=id..'\t'..hex(item.path)
                    end
                end
                if #lines>0 then
                    savePending()
                    state.sequence=state.sequence+1
                    local job=LrPathUtils.child(Config.work_root,Config.install_id..'-'..tostring(state.sequence))
                    LrFileUtils.createAllDirectories(job);write(LrPathUtils.child(job,'files.tsv'),table.concat(lines,'\n')..'\n')
                    local entry=Config.worker_prefix and shell(Config.worker_prefix) or (shell(Config.worker)..' worker')
                    local command=shell(Config.python)..' '..entry..' --job '..shell(job)..' --settings '..shell(Config.settings)
                    if WIN_ENV then command='"'..command..'"' end
                    local code=LrTasks.execute(command)
                    if code~=0 then error('Profile matcher failed; see '..job) end
                    local result=assert(io.open(LrPathUtils.child(job,'result.tsv'),'r'))
                    for line in result:lines() do
                        local id,action,name,identity,reason=line:match('^([^\t]+)\t([^\t]+)\t([^\t]*)\t([^\t]*)\t([^\t]*)$')
                        local item=id and selected[id]
                        if item then
                            if action=='apply' then
                                local status=Logic.apply(catalog,item.photo,unhex(name),unhex(identity),item.profile,
                                    function(photo) return Verification.render(photo,LrPathUtils.child(job,'verify-'..id)) end)
                                if status=='applied' then state.applied=state.applied+1 else state.skipped=state.skipped+1 end
                                if status=='awaiting_profile_reload' or status=='verification_failed' then
                                    state.blocked[id]=item
                                end
                                log(status..' id='..id..' profile='..unhex(name))
                            else
                                state.skipped=state.skipped+1;log('skip id='..id..' '..unhex(reason))
                            end
                            state.pending[id]=nil
                        end
                    end
                    result:close()
                    savePending()
                    local blocked=0;for _ in pairs(state.blocked) do blocked=blocked+1 end
                    state.status='Verified '..tostring(state.applied)..'; retained/skipped '..tostring(state.skipped)
                    if blocked>0 then
                        state.status=state.status..'; '..tostring(blocked)..' waiting for profile loading/verification. Restart Lightroom after installing a new DCP; queued imports resume automatically.'
                    end
                    write(Config.status,Config.install_id..'\nRUNNING\n'..state.status..'\n')
                end
            end
        end)
        if not ok then state.status=tostring(err);log('ERROR '..tostring(err)) end
        LrTasks.sleep(Config.interval or 5)
    end
end

return Runtime
