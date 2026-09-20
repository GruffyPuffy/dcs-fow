-- Mission-side FoW adapter. No files, sockets, or model logic run here.
FoWBridge = {}
-- Created each time this mission script loads, including mission restarts.
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
                        local speed = math.sqrt(velocity.x * velocity.x
                            + velocity.z * velocity.z)
                        local lat, lon = coord.LOtoLL(point)
                        units[#units + 1] = '{"id":' .. unit:getID()
                            .. ',"name":' .. quoted(unit:getName())
                            .. ',"type":' .. quoted(unit:getTypeName())
                            .. ',"x":' .. number(point.x)
                            .. ',"y":' .. number(point.y)
                            .. ',"z":' .. number(point.z)
                            .. ',"speed_mps":' .. number(speed)
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
    return '{"v":1,"id":' .. quoted(id) .. ',"ok":true,"mission_id":'
        .. quoted(FoWBridge.mission_id) .. ',"time":' .. number(timer.getTime())
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
    if op == 'set_roe' then
        local roe = {
            open_fire = AI.Option.Ground.val.ROE.OPEN_FIRE,
            return_fire = AI.Option.Ground.val.ROE.RETURN_FIRE,
            weapon_hold = AI.Option.Ground.val.ROE.WEAPON_HOLD,
        }
        if not roe[x] then return reply(id, false, 'INVALID_ROE') end
        group:getController():setOption(AI.Option.Ground.id.ROE, roe[x])
        return reply(id, true, 'ROE_ACCEPTED:' .. x)
    end
    if op == 'move_geo' then
        local point = coord.LLtoLO(x, z)
        x, z = point.x, point.z
    elseif op ~= 'move' then
        return reply(id, false, 'UNKNOWN_COMMAND')
    end
    local current = lead:getPoint()
    local dx, dz = x - current.x, z - current.z
    if dx * dx + dz * dz > 50000 * 50000 then
        return reply(id, false, 'TARGET_TOO_FAR')
    end
    local destination = { x = x, y = z }
    if land.getSurfaceType(destination) ~= land.SurfaceType.LAND then
        return reply(id, false, 'TARGET_NOT_LAND')
    end
    local route = { points = {
        [1] = { x = current.x, y = current.z, action = 'Off Road', speed = 5, speed_locked = true },
        [2] = { x = x, y = z, action = 'Off Road', speed = 5, speed_locked = true },
    } }
    group:getController():setTask({ id = 'Mission', params = { route = route } })
    return reply(id, true, 'MOVE_ACCEPTED')
end

local spawn_sequence = 0
function FoWBridge.spawn(id, side_name, template_name, lat, lon, requested_name)
    local side = side_name == 'blue' and coalition.side.BLUE or
        side_name == 'red' and coalition.side.RED or nil
    local catalog = FoWSpawnCatalog and FoWSpawnCatalog[side_name]
    local template = catalog and catalog[template_name]
    if not side or not template then return reply(id, false, 'UNKNOWN_TEMPLATE') end
    local point = coord.LLtoLO(lat, lon)
    local near_friendly = false
    for _, group in pairs(coalition.getGroups(side, Group.Category.GROUND) or {}) do
        if group and group:isExist() then
            local unit = group:getUnit(1)
            if unit and unit:isExist() then
                local pos = unit:getPoint()
                local dx, dz = point.x - pos.x, point.z - pos.z
                if dx * dx + dz * dz <= 50000 * 50000 then near_friendly = true; break end
            end
        end
    end
    if not near_friendly then return reply(id, false, 'NO_FRIENDLY_WITHIN_50KM') end
    local units = {}
    for index, entry in ipairs(template.units) do
        local x, y = point.x + entry.dx, point.z + entry.dy
        if land.getSurfaceType({x = x, y = y}) ~= land.SurfaceType.LAND then
            return reply(id, false, 'SPAWN_NOT_LAND')
        end
        units[index] = {type = entry.type, x = x, y = y, heading = 0,
                        skill = 'Average', playerCanDrive = false}
    end
    local group_name
    if requested_name and requested_name ~= '' then
        if #requested_name < 3 or #requested_name > 60
            or not requested_name:match('^[A-Za-z0-9_ -]+$')
            or requested_name:match('^ ') or requested_name:match(' $') then
            return reply(id, false, 'INVALID_NAME')
        end
        group_name = requested_name
        if Group.getByName(group_name) then return reply(id, false, 'NAME_IN_USE') end
    else
        spawn_sequence = spawn_sequence + 1
        local side_label = side_name == 'blue' and 'Blue' or 'Red'
        local label = template.label:gsub('[^A-Za-z0-9 _-]', ''):sub(1, 35)
        if label == '' then label = 'Unit' end
        group_name = string.format('FoW %s %s %03d', side_label, label, spawn_sequence)
        while Group.getByName(group_name) do
            spawn_sequence = spawn_sequence + 1
            group_name = string.format('FoW %s %s %03d', side_label, label, spawn_sequence)
        end
    end
    for index, unit in ipairs(units) do
        unit.name = group_name .. ' Unit ' .. index
        if Unit.getByName(unit.name) then return reply(id, false, 'UNIT_NAME_IN_USE') end
    end
    local country_id = side == coalition.side.BLUE and country.id.USA or country.id.RUSSIA
    local ok, group = pcall(coalition.addGroup, country_id, Group.Category.GROUND,
        {name = group_name, task = 'Ground Nothing', x = point.x, y = point.z,
         units = units, visible = true, hidden = false, start_time = 0})
    if not ok or not group then return reply(id, false, 'SPAWN_FAILED') end
    local option_ok = pcall(function()
        group:getController():setOption(AI.Option.Ground.id.ROE, AI.Option.Ground.val.ROE.OPEN_FIRE)
    end)
    return reply(id, true, 'SPAWN_ACCEPTED:' .. group_name
        .. (option_ok and ';ROE=OPEN_FIRE' or ';ROE=UNKNOWN'))
end

local air_sequence = 0
function FoWBridge.airMove(id, group_name, lat, lon, altitude_m)
    local group = Group.getByName(group_name)
    if not group or not group:isExist() then return reply(id, false, 'GROUP_MISSING') end
    if group:getCategory() ~= Group.Category.AIRPLANE then return reply(id, false, 'NOT_AIRCRAFT') end
    if group:getCoalition() ~= coalition.side.BLUE and group:getCoalition() ~= coalition.side.RED then
        return reply(id, false, 'INVALID_COALITION')
    end
    local units = group:getUnits() or {}
    local lead = units[1]
    if not lead or not lead:isExist() then return reply(id, false, 'UNIT_MISSING') end
    for _, unit in pairs(units) do
        if unit:getPlayerName() then return reply(id, false, 'PLAYER_CONTROLLED') end
    end
    local current, destination = lead:getPoint(), coord.LLtoLO(lat, lon)
    local dx, dz = destination.x - current.x, destination.z - current.z
    if dx * dx + dz * dz < 2000 * 2000 or dx * dx + dz * dz > 300000 * 300000 then
        return reply(id, false, 'AIR_TARGET_RANGE')
    end
    local function waypoint(x, z, altitude)
        return {x = x, y = z, alt = altitude, alt_type = 'BARO', speed = 210,
            type = 'Turning Point', action = 'Turning Point', speed_locked = true,
            ETA = 0, ETA_locked = false,
            task = {id = 'ComboTask', params = {tasks = {}}}}
    end
    local route = {points = {[1] = waypoint(current.x, current.z, math.max(1000, current.y)),
                           [2] = waypoint(destination.x, destination.z, altitude_m)}}
    local ok = pcall(function()
        group:getController():setTask({id = 'Mission', params = {route = route}})
    end)
    if not ok then return reply(id, false, 'AIR_ROUTE_FAILED') end
    return reply(id, true, 'AIR_MOVE_ACCEPTED')
end

local function copy_table(value)
    if type(value) ~= 'table' then return value end
    local result = {}
    for key, item in pairs(value) do result[key] = copy_table(item) end
    return result
end

function FoWBridge.spawnAir(id, side_name, preset_name, lat, lon, requested_name)
    local air_presets = FoWAirCatalog and FoWAirCatalog.presets and FoWAirCatalog.presets[side_name]
    local preset = air_presets and air_presets[preset_name]
    if not preset then return reply(id, false, 'UNKNOWN_AIR_PRESET') end
    local data = copy_table(preset.group)
    local destination = coord.LLtoLO(lat, lon)
    local dx, dy = destination.x - data.x, destination.z - data.y
    local distance_sq = dx * dx + dy * dy
    if distance_sq < 5000 * 5000 or distance_sq > 150000 * 150000 then
        return reply(id, false, 'AIR_WAYPOINT_RANGE')
    end
    local name
    if requested_name and requested_name ~= '' then
        if #requested_name < 3 or #requested_name > 60
            or not requested_name:match('^[A-Za-z0-9_ -]+$')
            or requested_name:match('^ ') or requested_name:match(' $') then
            return reply(id, false, 'INVALID_NAME')
        end
        name = requested_name
        if Group.getByName(name) then return reply(id, false, 'NAME_IN_USE') end
    else
        air_sequence = air_sequence + 1
        name = string.format('FoW %s %s %03d', side_name == 'blue' and 'Blue' or 'Red',
            preset.label:gsub('[^A-Za-z0-9 ]', ''):sub(1, 20), air_sequence)
        while Group.getByName(name) do
            air_sequence = air_sequence + 1
            name = string.format('FoW %s %s %03d', side_name == 'blue' and 'Blue' or 'Red',
                preset.label:gsub('[^A-Za-z0-9 ]', ''):sub(1, 20), air_sequence)
        end
    end
    data.name = name
    data.groupId = nil
    local unit = data.units[1]
    unit.name = name .. ' Pilot 1'
    unit.unitId = nil
    unit.skill = 'High'
    if Unit.getByName(unit.name) then return reply(id, false, 'UNIT_NAME_IN_USE') end
    
    -- Set waypoint at mission point with altitude from preset
    -- For CAP, use proper DCS CAP task; for patrol, simple orbit
    local waypoint_task = {id = 'ComboTask', params = {tasks = {}}}
    if preset.mission_type == 'CAP' then
        waypoint_task = {
            id = 'ComboTask',
            params = {
                tasks = {
                    [1] = {
                        id = 'CAP',
                        params = {
                            x = destination.x,
                            y = destination.z,
                            alt = preset.altitude_m,
                            speed = preset.speed_mps,
                            pattern = 'Circle',
                            priority = 0
                        }
                    }
                }
            }
        }
    elseif preset.mission_type == 'patrol' then
        waypoint_task = {
            id = 'ComboTask',
            params = {
                tasks = {
                    [1] = {
                        id = 'Orbit',
                        params = {
                            pattern = 'Circle',
                            speed = preset.speed_mps,
                            altitude = preset.altitude_m
                        }
                    }
                }
            }
        }
    end
    data.route.points[2] = {
        x = destination.x, y = destination.z, alt = preset.altitude_m, alt_type = 'BARO',
        speed = preset.speed_mps, speed_locked = true, ETA = 0, ETA_locked = false,
        type = 'Turning Point', action = 'Turning Point', name = 'Mission point',
        task = waypoint_task,
    }
    local country_id = side_name == 'blue' and country.id.USA or country.id.RUSSIA
    local ok, group = pcall(coalition.addGroup, country_id, Group.Category.AIRPLANE, data)
    if not ok or not group then return reply(id, false, 'AIR_SPAWN_FAILED') end
    return reply(id, true, 'AIR_SPAWN_ACCEPTED:' .. name .. ';MISSION=' .. preset.mission_type)
end

function FoWBridge.setMission(id, group_name, mission_type, lat, lon, altitude_m)
    local group = Group.getByName(group_name)
    if not group or not group:isExist() then return reply(id, false, 'GROUP_MISSING') end
    if group:getCategory() ~= Group.Category.AIRPLANE then return reply(id, false, 'NOT_AIRCRAFT') end
    if group:getCoalition() ~= coalition.side.BLUE and group:getCoalition() ~= coalition.side.RED then
        return reply(id, false, 'INVALID_COALITION')
    end
    local units = group:getUnits() or {}
    for _, unit in pairs(units) do
        if unit:getPlayerName() then return reply(id, false, 'PLAYER_CONTROLLED') end
    end
    local lead = units[1]
    if not lead or not lead:isExist() then return reply(id, false, 'UNIT_MISSING') end
    local destination = coord.LLtoLO(lat, lon)
    local current = lead:getPoint()
    local dx, dz = destination.x - current.x, destination.z - current.z
    if dx * dx + dz * dz < 2000 * 2000 or dx * dx + dz * dz > 300000 * 300000 then
        return reply(id, false, 'AIR_TARGET_RANGE')
    end
    local function waypoint(x, z, altitude, speed)
        local task = {id = 'ComboTask', params = {tasks = {}}}
        if mission_type == 'CAP' then
            task = {
                id = 'ComboTask',
                params = {
                    tasks = {
                        [1] = {
                            id = 'CAP',
                            params = {
                                x = x,
                                y = z,
                                alt = altitude,
                                speed = speed,
                                pattern = 'Circle',
                                priority = 0
                            }
                        }
                    }
                }
            }
        elseif mission_type == 'patrol' then
            task = {
                id = 'ComboTask',
                params = {
                    tasks = {
                        [1] = {
                            id = 'Orbit',
                            params = {
                                pattern = 'Circle',
                                speed = speed,
                                altitude = altitude
                            }
                        }
                    }
                }
            }
        end
        return {x = x, y = z, alt = altitude, alt_type = 'BARO', speed = speed,
            type = 'Turning Point', action = 'Turning Point', speed_locked = true,
            ETA = 0, ETA_locked = false, task = task}
    end
    local route = {points = {[1] = waypoint(current.x, current.z, math.max(1000, current.y), 210),
                           [2] = waypoint(destination.x, destination.z, altitude_m, 210)}}
    local ok = pcall(function()
        group:getController():setTask({id = 'Mission', params = {route = route}})
    end)
    if not ok then return reply(id, false, 'MISSION_SET_FAILED') end
    return reply(id, true, 'MISSION_SET:' .. mission_type)
end

function FoWBridge.rtbCommand(id, group_name, airbase_name)
    local group = Group.getByName(group_name)
    if not group or not group:isExist() then return reply(id, false, 'GROUP_MISSING') end
    if group:getCategory() ~= Group.Category.AIRPLANE then return reply(id, false, 'NOT_AIRCRAFT') end
    local units = group:getUnits() or {}
    for _, unit in pairs(units) do
        if unit:getPlayerName() then return reply(id, false, 'PLAYER_CONTROLLED') end
    end
    local airbase = Airbase.getByName(airbase_name)
    if not airbase then return reply(id, false, 'AIRBASE_NOT_FOUND') end
    local ok = pcall(function()
        group:getController():setTask({
            id = 'Land',
            params = {durationFlag = false, airdromeId = airbase:getID()}
        })
    end)
    if not ok then return reply(id, false, 'RTB_FAILED') end
    return reply(id, true, 'RTB_ACCEPTED:' .. airbase_name)
end

-- The hook passes data here. Keep the operation allowlist and DCS-specific
-- validation in mission space, so new commands need only a mission update.
local function valid_number(value, limit)
    return type(value) == 'number' and value == value
        and value ~= math.huge and value ~= -math.huge and math.abs(value) <= limit
end

local function valid_geo(request)
    return valid_number(request.lat, 90) and valid_number(request.lon, 180)
end

local function valid_group_name(value)
    return type(value) == 'string' and #value >= 1 and #value <= 128
end

local function valid_custom_name(value)
    return value == nil or (type(value) == 'string' and #value <= 60
        and (value == '' or (#value >= 3 and value:match('^[A-Za-z0-9_ -]+$')
            and not value:match('^ ') and not value:match(' $'))))
end

function FoWBridge.handle(request)
    local id = request.id
    local op = request.op
    if op == 'status' then return FoWBridge.status(id) end
    local valid_side = request.side == 'blue' or request.side == 'red'
    if op == 'spawn' then
        if not valid_side or type(request.template) ~= 'string' or #request.template < 1
            or #request.template > 32 or not request.template:match('^[%w_-]+$')
            or not valid_geo(request) or not valid_custom_name(request.name) then
            return reply(id, false, 'INVALID_SPAWN')
        end
        return FoWBridge.spawn(id, request.side, request.template,
            request.lat, request.lon, request.name or '')
    end
    if op == 'spawn_air' then
        if not valid_side or type(request.preset) ~= 'string' or #request.preset < 1
            or #request.preset > 32 or not request.preset:match('^[%w_-]+$')
            or not valid_geo(request) or not valid_custom_name(request.name) then
            return reply(id, false, 'INVALID_AIR_SPAWN')
        end
        return FoWBridge.spawnAir(id, request.side, request.preset,
            request.lat, request.lon, request.name or '')
    end
    if op == 'set_mission' then
        if not valid_group_name(request.group) or not valid_geo(request)
            or not valid_number(request.altitude_m, 12000) or request.altitude_m < 1000
            or (request.mission_type ~= 'patrol' and request.mission_type ~= 'CAP') then
            return reply(id, false, 'INVALID_SET_MISSION')
        end
        return FoWBridge.setMission(id, request.group, request.mission_type,
            request.lat, request.lon, request.altitude_m)
    end
    if op == 'rtb' then
        if not valid_group_name(request.group) or type(request.airbase) ~= 'string'
            or #request.airbase < 1 or #request.airbase > 64 then
            return reply(id, false, 'INVALID_RTB')
        end
        return FoWBridge.rtbCommand(id, request.group, request.airbase)
    end
    if not valid_group_name(request.group) then return reply(id, false, 'INVALID_GROUP') end
    if op == 'air_move' then
        if not valid_geo(request) or not valid_number(request.altitude_m, 12000)
            or request.altitude_m < 1000 then return reply(id, false, 'INVALID_AIR_MOVE') end
        return FoWBridge.airMove(id, request.group, request.lat,
            request.lon, request.altitude_m)
    end
    if op == 'hold' then return FoWBridge.command(id, op, request.group) end
    if op == 'set_roe' then
        if request.mode ~= 'open_fire' and request.mode ~= 'return_fire'
            and request.mode ~= 'weapon_hold' then return reply(id, false, 'INVALID_ROE') end
        return FoWBridge.command(id, op, request.group, request.mode)
    end
    if op == 'move_geo' then
        if not valid_geo(request) then return reply(id, false, 'INVALID_DESTINATION') end
        return FoWBridge.command(id, op, request.group, request.lat, request.lon)
    end
    if op == 'move' then
        if not valid_number(request.x, 10000000) or not valid_number(request.z, 10000000) then
            return reply(id, false, 'INVALID_DESTINATION')
        end
        return FoWBridge.command(id, op, request.group, request.x, request.z)
    end
    return reply(id, false, 'UNKNOWN_COMMAND')
end

env.info('FOW_BRIDGE_READY')
