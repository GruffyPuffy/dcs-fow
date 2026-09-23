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

-- Apply once per ground group. Later commander overrides must remain intact.
local ground_roe = {}
local function default_ground_roe(group)
    if group:getCategory() ~= Group.Category.GROUND then return end
    local key = group:getName() .. ':' .. group:getID()
    if ground_roe[key] then return end
    group:getController():setOption(AI.Option.Ground.id.ROE, AI.Option.Ground.val.ROE.OPEN_FIRE)
    ground_roe[key] = 'open_fire'
end

-- Retain a bounded event tail so polling does not consume or duplicate events.
local kill_reports, kill_sequence, killed_targets = {}, 0, {}
local function safe_call(object, method)
    if not object then return nil end
    local ok, value = pcall(function() return object[method](object) end)
    if ok then return value end
end
local kill_handler = {}
function kill_handler:onEvent(event)
    if event.id ~= world.event.S_EVENT_KILL then return end
    local target_id = safe_call(event.target, 'getID')
    if not target_id or killed_targets[target_id] then return end
    killed_targets[target_id] = true
    kill_sequence = kill_sequence + 1
    local attacker_group = safe_call(event.initiator, 'getGroup')
    local weapon_type = event.weapon_name or safe_call(event.weapon, 'getTypeName')
    kill_reports[#kill_reports + 1] = '{"id":' .. kill_sequence
        .. ',"time":' .. number(event.time or timer.getTime())
        .. ',"target_id":' .. target_id
        .. ',"target_side":' .. (safe_call(event.target, 'getCoalition') or 0)
        .. ',"target_type":' .. quoted(safe_call(event.target, 'getTypeName') or 'Unknown target')
        .. ',"side":' .. (safe_call(event.initiator, 'getCoalition') or 0)
        .. ',"attacker":' .. quoted(safe_call(event.initiator, 'getName') or 'Unknown attacker')
        .. ',"attacker_group":' .. quoted(safe_call(attacker_group, 'getName') or '')
        .. ',"weapon":' .. quoted(weapon_type or 'Unknown') .. '}'
    if #kill_reports > 200 then table.remove(kill_reports, 1) end
end
world.addEventHandler(kill_handler)

-- Only current, range-resolved radar reports from AI AWACS aircraft.
-- Never read live enemy positions for remembered or bearing-only detections.
local function awacs_reports(unit, side)
    if side == coalition.side.NEUTRAL or unit:getPlayerName()
            or not unit:hasAttribute('AWACS') then return {} end
    local reports = {}
    local controller = unit:getController()
    for _, detection in pairs(controller:getDetectedTargets(Controller.Detection.RADAR) or {}) do
        local target = detection.object
        if detection.visible and detection.distance and target and target:isExist()
                and target:getCategory() == Object.Category.UNIT
                and target:getCoalition() == (side == coalition.side.BLUE and coalition.side.RED or coalition.side.BLUE) then
            local category = target:getDesc().category
            if category == Unit.Category.AIRPLANE or category == Unit.Category.HELICOPTER then
                local point = target:getPoint()
                local lat, lon = coord.LOtoLL(point)
                local identified = detection.type and ',"type":' .. quoted(target:getTypeName()) or ''
                reports[#reports + 1] = '{"side":' .. side
                    .. ',"target_id":' .. target:getID()
                    .. ',"source":' .. quoted(unit:getName())
                    .. ',"lat":' .. geo_number(lat) .. ',"lon":' .. geo_number(lon)
                    .. ',"altitude_m":' .. number(point.y) .. identified .. '}'
            end
        end
    end
    return reports
end

function FoWBridge.status(id)
    local groups, statics, airbases, reports = {}, {}, {}, {}
    local sensor_errors = 0
    for _, side in ipairs(sides) do
        for _, group in pairs(coalition.getGroups(side) or {}) do
            if group and group:isExist() then
                local units = {}
                for _, unit in pairs(group:getUnits() or {}) do
                    if unit and unit:isExist() then
                        if group:getCategory() == Group.Category.AIRPLANE then
                            local ok, detected = pcall(awacs_reports, unit, side)
                            if ok then
                                for _, report in ipairs(detected) do reports[#reports + 1] = report end
                            else
                                sensor_errors = sensor_errors + 1
                            end
                        end
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
                    .. ',"roe":' .. quoted(ground_roe[group:getName() .. ':' .. group:getID()] or 'unknown')
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
    for _, airbase in pairs(world.getAirbases() or {}) do
        if airbase and airbase:isExist() then
            local point = airbase:getPoint()
            local lat, lon = coord.LOtoLL(point)
            airbases[#airbases + 1] = '{"id":' .. airbase:getID()
                .. ',"name":' .. quoted(airbase:getName())
                .. ',"coalition":' .. airbase:getCoalition()
                .. ',"category":' .. airbase:getCategory()
                .. ',"lat":' .. geo_number(lat)
                .. ',"lon":' .. geo_number(lon) .. '}'
        end
    end
    return '{"v":1,"id":' .. quoted(id) .. ',"ok":true,"mission_id":'
        .. quoted(FoWBridge.mission_id) .. ',"time":' .. number(timer.getTime())
        .. ',"kill_reports":[' .. table.concat(kill_reports, ',') .. ']'
        .. ',"awacs_reports":[' .. table.concat(reports, ',') .. ']'
        .. ',"awacs_sensor_errors":' .. sensor_errors
        .. ',"groups":[' .. table.concat(groups, ',') .. ']'
        .. ',"statics":[' .. table.concat(statics, ',') .. ']'
        .. ',"airbases":[' .. table.concat(airbases, ',') .. ']}'
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
    local configured = pcall(default_ground_roe, group)
    local suffix = category == Group.Category.GROUND and
        (configured and ';ROE=OPEN_FIRE' or ';ROE=UNKNOWN') or ''
    return reply(id, true, 'SPAWN_ACCEPTED:' .. group_data.name .. suffix)
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

function FoWBridge.setCommand(id, group_name, command_data)
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

    local prepared, resolved = pcall(resolve, command_data, 0)
    if not prepared then return reply(id, false, tostring(resolved)) end
    local ok = pcall(function() group:getController():setCommand(resolved) end)
    return reply(id, ok, ok and 'COMMAND_ACCEPTED' or 'COMMAND_FAILED')
end

function FoWBridge.setOption(id, group_name, option_id, value)
    local group = Group.getByName(group_name)
    if not group or not group:isExist() then
        return reply(id, false, 'GROUP_MISSING')
    end
    
    local ok = pcall(function()
        group:getController():setOption(option_id, value)
        if group:getCategory() == Group.Category.GROUND and option_id == AI.Option.Ground.id.ROE then
            local modes = {[AI.Option.Ground.val.ROE.OPEN_FIRE]='open_fire',
                [AI.Option.Ground.val.ROE.RETURN_FIRE]='return_fire',
                [AI.Option.Ground.val.ROE.WEAPON_HOLD]='weapon_hold'}
            ground_roe[group:getName() .. ':' .. group:getID()] = modes[value] or 'unknown'
        end
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
    elseif op == 'set_command' then
        return FoWBridge.setCommand(id, request.group_name, request.command_data)
    elseif op == 'set_option' then
        return FoWBridge.setOption(id, request.group_name, request.option_id, request.value)
    else
        return reply(id, false, 'UNKNOWN_OPERATION')
    end
end

-- Includes initial and late-activated groups; failed applications retry next pass.
-- Never reapply to a group whose ROE has already been set.
timer.scheduleFunction(function(_, now)
    for _, side in ipairs({coalition.side.RED, coalition.side.BLUE}) do
        for _, group in pairs(coalition.getGroups(side, Group.Category.GROUND) or {}) do
            if group and group:isExist() then pcall(default_ground_roe, group) end
        end
    end
    return now + 5
end, nil, timer.getTime() + 1)

trigger.action.outText('FOW_BRIDGE_READY', 1)
