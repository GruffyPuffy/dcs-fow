-- Generic FoW bridge: resolves DCS-runtime references and applies server-built tables.
FoWBridge = {}
FoWBridge.mission_id = tostring({}) .. ':' .. tostring(math.random(0, 2147483647))
    .. ':' .. tostring(timer.getAbsTime())

local function quoted(value)
    return '"' .. tostring(value):gsub('[%z\1-\31\\"]', function(c)
        if c == '\\' then return '\\\\' end
        if c == '"' then return '\\"' end
        return string.format('\\u%04x', string.byte(c))
    end) .. '"'
end

local function number(value)
    return string.format('%.1f', value)
end

local function geo_number(value)
    return string.format('%.6f', value)
end

local function reply(id, ok, result)
    return '{"v":1,"id":' .. quoted(id) .. ',"ok":' .. tostring(ok)
        .. ',"result":' .. quoted(result) .. '}'
end

local sides = { coalition.side.NEUTRAL, coalition.side.RED, coalition.side.BLUE }

function FoWBridge.status(id)
    local groups, statics = {}, {}
    for _, side in ipairs(sides) do
        for _, group in pairs(coalition.getGroups(side) or {}) do
            if group and group:isExist() then
                local units = {}
                for _, unit in pairs(group:getUnits() or {}) do
                    if unit and unit:isExist() then
                        local point = unit:getPoint()
                        local velocity = unit:getVelocity()
                        local speed = math.sqrt(velocity.x * velocity.x + velocity.z * velocity.z)
                        local lat, lon = coord.LOtoLL(point)
                        local fuel = ''
                        local callsign = ''
                        if group:getCategory() == Group.Category.AIRPLANE
                                or group:getCategory() == Group.Category.HELICOPTER then
                            fuel = ',"fuel":' .. number(unit:getFuel())
                            callsign = ',"callsign":' .. quoted(unit:getCallsign())
                        end
                        units[#units + 1] = '{"id":' .. unit:getID()
                            .. ',"name":' .. quoted(unit:getName())
                            .. ',"type":' .. quoted(unit:getTypeName())
                            .. ',"x":' .. number(point.x)
                            .. ',"y":' .. number(point.y)
                            .. ',"z":' .. number(point.z)
                            .. ',"speed_mps":' .. number(speed)
                            .. ',"lat":' .. geo_number(lat)
                            .. ',"lon":' .. geo_number(lon)
                            .. fuel .. callsign .. '}'
                    end
                end
                groups[#groups + 1] = '{"id":' .. group:getID()
                    .. ',"name":' .. quoted(group:getName())
                    .. ',"coalition":' .. side
                    .. ',"category":' .. group:getCategory()
                    .. ',"units":[' .. table.concat(units, ',') .. ']}'
            end
        end
        for _, object in pairs(coalition.getStaticObjects(side) or {}) do
            if object and object:isExist() then
                local point = object:getPoint()
                local lat, lon = coord.LOtoLL(point)
                statics[#statics + 1] = '{"name":' .. quoted(object:getName())
                    .. ',"type":' .. quoted(object:getTypeName())
                    .. ',"coalition":' .. side
                    .. ',"x":' .. number(point.x)
                    .. ',"y":' .. number(point.y)
                    .. ',"z":' .. number(point.z)
                    .. ',"lat":' .. geo_number(lat)
                    .. ',"lon":' .. geo_number(lon) .. '}'
            end
        end
    end
    return '{"v":1,"id":' .. quoted(id) .. ',"ok":true,"mission_id":'
        .. quoted(FoWBridge.mission_id) .. ',"time":' .. number(timer.getTime())
        .. ',"groups":[' .. table.concat(groups, ',') .. ']'
        .. ',"statics":[' .. table.concat(statics, ',') .. ']}'
end

local function resolve(value, depth)
    if type(value) ~= 'table' then return value end
    if depth > 20 then error('RESOLVE_DEPTH') end
    if value.__ref == 'airbase_id' then
        local airbase = Airbase.getByName(value.name)
        if not airbase then error('AIRBASE_NOT_FOUND') end
        return airbase:getID()
    end
    local geo = value.__geo
    if geo then
        local point = coord.LLtoLO(geo.lat, geo.lon)
        value.x, value.y, value.__geo = point.x, point.z, nil
    end
    for key, item in pairs(value) do value[key] = resolve(item, depth + 1) end
    return value
end

function FoWBridge.spawnGroup(id, country_id, category, group_data)
    if Group.getByName(group_data.name) then
        return reply(id, false, 'NAME_IN_USE')
    end
    local prepared, resolved = pcall(resolve, group_data, 0)
    if not prepared then return reply(id, false, tostring(resolved)) end
    local ok, group = pcall(coalition.addGroup, country_id, category, resolved)
    if not ok or not group then
        return reply(id, false, 'SPAWN_FAILED')
    end
    return reply(id, true, 'SPAWN_ACCEPTED:' .. group_data.name)
end

function FoWBridge.setRoute(id, group_name, route_data)
    local group = Group.getByName(group_name)
    if not group or not group:isExist() then
        return reply(id, false, 'GROUP_MISSING')
    end
    
    local units = group:getUnits() or {}
    for _, unit in pairs(units) do
        if unit:getPlayerName() then
            return reply(id, false, 'PLAYER_CONTROLLED')
        end
    end
    
    local prepared, resolved = pcall(resolve, route_data, 0)
    if not prepared then return reply(id, false, tostring(resolved)) end
    local ok = pcall(function()
        group:getController():setTask({id = 'Mission', params = {route = resolved}})
    end)
    
    if not ok then
        return reply(id, false, 'ROUTE_FAILED')
    end
    
    return reply(id, true, 'ROUTE_ACCEPTED')
end

function FoWBridge.setTask(id, group_name, task_data)
    local group = Group.getByName(group_name)
    if not group or not group:isExist() then
        return reply(id, false, 'GROUP_MISSING')
    end
    
    local units = group:getUnits() or {}
    for _, unit in pairs(units) do
        if unit:getPlayerName() then
            return reply(id, false, 'PLAYER_CONTROLLED')
        end
    end
    
    local prepared, resolved = pcall(resolve, task_data, 0)
    if not prepared then return reply(id, false, tostring(resolved)) end
    local ok = pcall(function() group:getController():setTask(resolved) end)
    return reply(id, ok, ok and 'TASK_ACCEPTED' or 'TASK_FAILED')
end

function FoWBridge.setOption(id, group_name, option_id, value)
    local group = Group.getByName(group_name)
    if not group or not group:isExist() then
        return reply(id, false, 'GROUP_MISSING')
    end
    
    local ok = pcall(function()
        group:getController():setOption(option_id, value)
    end)
    
    if not ok then
        return reply(id, false, 'OPTION_FAILED')
    end
    
    return reply(id, true, 'OPTION_SET')
end

function FoWBridge.handle(request)
    local id = request.id
    local op = request.op
    
    if op == 'status' then
        return FoWBridge.status(id)
    elseif op == 'spawn_group' then
        return FoWBridge.spawnGroup(id, request.country_id, request.category, 
            request.group_data)
    elseif op == 'set_route' then
        return FoWBridge.setRoute(id, request.group_name, request.route_data)
    elseif op == 'set_task' then
        return FoWBridge.setTask(id, request.group_name, request.task_data)
    elseif op == 'set_option' then
        return FoWBridge.setOption(id, request.group_name, request.option_id, request.value)
    else
        return reply(id, false, 'UNKNOWN_OPERATION')
    end
end

trigger.action.outText('FOW_BRIDGE_READY', 1)
