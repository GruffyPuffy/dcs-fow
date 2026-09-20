-- Experimental extension appended to the baseline mission Lua for one test.
local baseline_command = FoWBridge.command
local move_target = nil

function FoWBridge.command(token)
    if token ~= "BLUE_MOVE_TEST" then
        return baseline_command(token)
    end

    local group = Group.getByName("FoW Blue Ground")
    if not group or not group:isExist() then
        env.info("FOW_RESULT;BLUE_MOVE_TEST;rejected;GROUP_MISSING")
        return "GROUP_MISSING"
    end
    local unit = group:getUnits()[1]
    if not unit or not unit:isExist() then
        env.info("FOW_RESULT;BLUE_MOVE_TEST;rejected;UNIT_MISSING")
        return "UNIT_MISSING"
    end

    local pos = unit:getPoint()
    local destination = { x = pos.x + 150, y = pos.z + 150 }
    if land.getSurfaceType(destination) ~= land.SurfaceType.LAND then
        env.info("FOW_RESULT;BLUE_MOVE_TEST;rejected;TARGET_NOT_LAND")
        return "TARGET_NOT_LAND"
    end

    local route = {
        points = {
            [1] = { x = pos.x, y = pos.z, action = "Off Road", speed = 5, speed_locked = true },
            [2] = { x = destination.x, y = destination.y, action = "Off Road", speed = 5, speed_locked = true },
        },
    }
    group:getController():setTask({ id = "Mission", params = { route = route } })
    move_target = destination
    env.info(string.format("FOW_RESULT;BLUE_MOVE_TEST;accepted;%.1f;%.1f", destination.x, destination.y))
    return "MOVE_ACCEPTED"
end

local function check_move(_, now)
    if move_target then
        local group = Group.getByName("FoW Blue Ground")
        local unit = group and group:isExist() and group:getUnits()[1]
        if not unit or not unit:isExist() then
            env.info("FOW_RESULT;BLUE_MOVE_TEST;failed;UNIT_MISSING")
            move_target = nil
        else
            local pos = unit:getPoint()
            local dx, dz = pos.x - move_target.x, pos.z - move_target.y
            if dx * dx + dz * dz <= 25 * 25 then
                env.info("FOW_RESULT;BLUE_MOVE_TEST;completed")
                move_target = nil
            end
        end
    end
    return now + 5
end

timer.scheduleFunction(check_move, nil, timer.getTime() + 5)
env.info("FOW_MOVE_CANDIDATE_READY")
