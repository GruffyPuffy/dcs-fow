-- Mission-side FoW adapter. No files, sockets, or model logic run here.
FoWBridge = {}

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
                        local lat, lon = coord.LOtoLL(point)
                        units[#units + 1] = '{"id":' .. unit:getID()
                            .. ',"name":' .. quoted(unit:getName())
                            .. ',"type":' .. quoted(unit:getTypeName())
                            .. ',"x":' .. number(point.x)
                            .. ',"y":' .. number(point.y)
                            .. ',"z":' .. number(point.z)
                            .. ',"lat":' .. geo_number(lat)
                            .. ',"lon":' .. geo_number(lon) .. '}'
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
    return '{"v":1,"id":' .. quoted(id) .. ',"ok":true,"time":' .. number(timer.getTime())
        .. ',"groups":[' .. table.concat(groups, ',') .. ']'
        .. ',"statics":[' .. table.concat(statics, ',') .. ']}'
end

function FoWBridge.command(id, op, group_name, x, z)
    local group = Group.getByName(group_name)
    if not group or not group:isExist() then return reply(id, false, 'GROUP_MISSING') end
    if group:getCategory() ~= Group.Category.GROUND then
        return reply(id, false, 'NOT_GROUND_GROUP')
    end
    if group:getCoalition() ~= coalition.side.RED and group:getCoalition() ~= coalition.side.BLUE then
        return reply(id, false, 'INVALID_COALITION')
    end
    local units = group:getUnits() or {}
    local lead = units[1]
    if not lead or not lead:isExist() then return reply(id, false, 'UNIT_MISSING') end
    for _, unit in pairs(units) do
        if unit:getPlayerName() then return reply(id, false, 'PLAYER_CONTROLLED') end
    end
    if op == 'hold' then
        group:getController():setTask({ id = 'Hold', params = {} })
        return reply(id, true, 'HOLD_ACCEPTED')
    end
    if op ~= 'move' then return reply(id, false, 'UNKNOWN_COMMAND') end
    local destination = { x = x, y = z }
    if land.getSurfaceType(destination) ~= land.SurfaceType.LAND then
        return reply(id, false, 'TARGET_NOT_LAND')
    end
    local current = lead:getPoint()
    local route = { points = {
        [1] = { x = current.x, y = current.z, action = 'Off Road', speed = 5, speed_locked = true },
        [2] = { x = x, y = z, action = 'Off Road', speed = 5, speed_locked = true },
    } }
    group:getController():setTask({ id = 'Mission', params = { route = route } })
    return reply(id, true, 'MOVE_ACCEPTED')
end

env.info('FOW_BRIDGE_READY')
