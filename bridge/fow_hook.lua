-- Saved Games/Scripts/Hooks extension. Stock DCS installation is unchanged.
-- Only fixed tokens are accepted; command file contents never become Lua code.
local root = lfs.writedir() .. "FoW/"
local command_path = root .. "command.txt"
local ack_path = root .. "ack.txt"
local allowed = { PING = true, BLUE_HOLD = true, RED_HOLD = true }
local frame = 0

local function acknowledge(token, result)
    local file = io.open(ack_path, "a")
    if file then
        file:write(os.date("!%Y-%m-%dT%H:%M:%SZ"), ";", token, ";", tostring(result), "\n")
        file:close()
    end
    log.write("FoW", log.INFO, "command " .. token .. ": " .. tostring(result))
end

local function poll()
    local file = io.open(command_path, "r")
    if not file then return end
    local token = file:read("*l")
    file:close()
    os.remove(command_path)
    if not allowed[token] then
        acknowledge(tostring(token), "REJECTED")
        return
    end
    local code = 'return a_do_script([[return FoWBridge.command("' .. token .. '")]])'
    local result = net.dostring_in("mission", code)
    -- This DCS build can execute a_do_script without returning its value to
    -- the hook. The mission's FOW_ACK log line is the execution receipt.
    if result == nil or result == "" then result = "DISPATCHED_NO_RETURN" end
    acknowledge(token, result)
end

DCS.setUserCallbacks({
    onSimulationFrame = function()
        frame = frame + 1
        if frame % 60 ~= 0 then return end
        local ok, err = pcall(poll)
        if not ok then log.write("FoW", log.ERROR, tostring(err)) end
    end,
})
log.write("FoW", log.INFO, "hook loaded")
