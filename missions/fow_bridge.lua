-- Runs inside the stock DCS mission scripting environment.
-- This file is embedded in fow.miz by build_mission.py.
FoWBridge = {}

local groups = {
    BLUE_HOLD = "FoW Blue Ground",
    RED_HOLD = "FoW Red Ground",
}

local function describe(name)
    local group = Group.getByName(name)
    if not group or not group:isExist() then
        return name .. ";missing"
    end
    local units = group:getUnits()
    local unit = units and units[1]
    if not unit or not unit:isExist() then
        return name .. ";empty"
    end
    local pos = unit:getPoint()
    return string.format("%s;alive;%.1f;%.1f", name, pos.x, pos.z)
end

function FoWBridge.status()
    return "FOW_STATUS;" .. describe(groups.BLUE_HOLD) .. ";" .. describe(groups.RED_HOLD)
end

function FoWBridge.command(token)
    if token == "PING" then
        env.info("FOW_ACK;PING")
        return "PING_OK"
    end
    local name = groups[token]
    if not name then
        return "UNKNOWN_COMMAND"
    end
    local group = Group.getByName(name)
    if not group or not group:isExist() then
        return "GROUP_MISSING"
    end
    group:getController():setTask({ id = "Hold", params = {} })
    env.info("FOW_ACK;" .. token)
    return token .. "_OK"
end

local function report(_, now)
    env.info(FoWBridge.status())
    return now + 10
end

timer.scheduleFunction(report, nil, timer.getTime() + 10)
env.info("FOW_BRIDGE_READY")
