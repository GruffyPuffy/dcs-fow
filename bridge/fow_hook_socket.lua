-- Candidate Saved Games hook: bounded line protocol over a local TCP port.
-- Docker publishes this port only on the Ubuntu host's loopback interface.
local socket = require("socket")
local listener, bind_error = socket.bind("0.0.0.0", 10309, 1)
if not listener then
    log.write("FoW", log.ERROR, "socket bind failed: " .. tostring(bind_error))
    return
end
listener:settimeout(0)

local client, input, output, sent = nil, "", nil, 1
local function close_client()
    if client then client:close() end
    client, input, output, sent = nil, "", nil, 1
end

local function mission_call(expression)
    -- Some DCS builds drop the first single return value from a_do_script.
    -- Request two values and read the second; this is deliberately tested live.
    local inner = 'return ' .. expression .. ', "SENTINEL"'
    local code = 'local _, value = a_do_script(' .. string.format('%q', inner) .. '); return value'
    local value, ok = net.dostring_in("mission", code)
    if not ok or type(value) ~= "string" or value == "" then
        return "ERR NO_MISSION_RETURN"
    end
    return value
end

local function handle(request)
    if request == "PING" then return "OK HOOK_PONG" end
    if request == "STATUS" then return mission_call("FoWBridge.status()") end
    if request == "BLUE_MOVE_TEST" then return mission_call('FoWBridge.command("BLUE_MOVE_TEST")') end
    return "ERR UNKNOWN_COMMAND"
end

local function frame()
    if not client then
        client = listener:accept()
        if not client then return end
        client:settimeout(0)
        input, output, sent = "", nil, 1
    end
    if not output then
        local line, err, partial = client:receive("*l")
        input = input .. (line or partial or "")
        if #input > 128 then
            output = "ERR REQUEST_TOO_LONG\n"
        elseif line then
            output = handle(input) .. "\n"
        elseif err == "closed" then
            close_client()
            return
        else
            return
        end
    end
    local next_byte, err, last_byte = client:send(output, sent)
    sent = (next_byte or last_byte or sent - 1) + 1
    if sent > #output or (err and err ~= "timeout") then close_client() end
end

DCS.setUserCallbacks({
    onSimulationFrame = function()
        local ok, err = pcall(frame)
        if not ok then
            log.write("FoW", log.ERROR, "socket frame: " .. tostring(err))
            close_client()
        end
    end,
    onSimulationStop = function()
        close_client()
    end,
})
log.write("FoW", log.INFO, "socket candidate listening on 10309")
