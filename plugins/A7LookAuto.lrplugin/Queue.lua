-- Persist only imports awaiting a new profile; do not rescan old edits.
local Queue = {}
local function hex(value) return ((value or ''):gsub('.',function(c) return string.format('%02x',c:byte()) end)) end
local function unhex(value) return (value:gsub('..',function(c) return string.char(tonumber(c,16)) end)) end

function Queue.read(path)
    local result={};local file=io.open(path,'r')
    if not file then return result end
    for line in file:lines() do
        local catalog,id,photo,observed=line:match('^([^\t]*)\t(%d+)\t([^\t]*)\t([^\t]*)$')
        if catalog then result[#result+1]={catalog=unhex(catalog),id=id,path=unhex(photo),profile=unhex(observed)} end
    end
    file:close();return result
end

function Queue.write(path, rows)
    local file=assert(io.open(path,'w'))
    for _,row in ipairs(rows) do
        file:write(hex(row.catalog)..'\t'..row.id..'\t'..hex(row.path)..'\t'..hex(row.profile)..'\n')
    end
    file:close()
end

return Queue
