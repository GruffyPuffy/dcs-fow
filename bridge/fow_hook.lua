-- Saved Games hook: local JSON-line bridge. DCS installation files are untouched.
local socket = require('socket')
local listener, bind_error = socket.bind('0.0.0.0', 10309, 1)
if not listener then
    log.write('FoW', log.ERROR, 'socket bind failed: ' .. tostring(bind_error))
    return
end
listener:settimeout(0)

local client, input, output, sent = nil, '', nil, 1
local function close_client()
    if client then client:close() end
    client, input, output, sent = nil, '', nil, 1
end

local function error_reply(id, reason)
    return '{"v":1,"id":"' .. id .. '","ok":false,"error":"' .. reason .. '"}'
end

local function mission_call(id, expression)
    -- This DCS build drops a single a_do_script return value. A second value
    -- makes the first available in the hook; tested on DCS 2.9.29.27468.
    local inner = 'return ' .. expression .. ', "SENTINEL"'
    local code = 'local _, value = a_do_script(' .. string.format('%q', inner) .. '); return value'
    local call_ok, value, dcs_ok = pcall(net.dostring_in, 'mission', code)
    if not call_ok or not dcs_ok or type(value) ~= 'string' or value:sub(1, 1) ~= '{' then
        return error_reply(id, 'NO_MISSION_RETURN')
    end
    if #value > 1048576 then return error_reply(id, 'RESPONSE_TOO_LARGE') end
    return value
end

local function handle(line)
    local parsed, request = pcall(net.json2lua, line)
    if not parsed or type(request) ~= 'table' then return error_reply('', 'INVALID_JSON') end
    local id = request.id
    if type(id) ~= 'string' or #id < 1 or #id > 64 or not id:match('^[%w_-]+$') then
        return error_reply('', 'INVALID_ID')
    end
    if request.v ~= 1 then return error_reply(id, 'UNSUPPORTED_VERSION') end
    if request.op == 'ping' then
        return '{"v":1,"id":"' .. id .. '","ok":true,"result":"pong"}'
    end
    if request.op == 'status' then
        return mission_call(id, 'FoWBridge.status(' .. string.format('%q', id) .. ')')
    end
    if request.op ~= 'move' and request.op ~= 'hold' then
        return error_reply(id, 'UNKNOWN_COMMAND')
    end
    local name = request.group
    if type(name) ~= 'string' or #name < 1 or #name > 128 then
        return error_reply(id, 'INVALID_GROUP')
    end
    local expression = 'FoWBridge.command(' .. string.format('%q', id) .. ','
        .. string.format('%q', request.op) .. ',' .. string.format('%q', name)
    if request.op == 'move' then
        local x, z = request.x, request.z
        if type(x) ~= 'number' or type(z) ~= 'number' or x ~= x or z ~= z
            or math.abs(x) > 10000000 or math.abs(z) > 10000000 then
            return error_reply(id, 'INVALID_DESTINATION')
        end
        expression = expression .. ',' .. string.format('%.3f', x) .. ',' .. string.format('%.3f', z)
    end
    return mission_call(id, expression .. ')')
end

local function frame()
    if not client then
        client = listener:accept()
        if not client then return end
        client:settimeout(0)
        input, output, sent = '', nil, 1
    end
    if not output then
        local line, err, partial = client:receive('*l')
        input = input .. (line or partial or '')
        if #input > 4096 then
            output = error_reply('', 'REQUEST_TOO_LARGE') .. '\n'
        elseif line then
            output = handle(input) .. '\n'
        elseif err == 'closed' then
            close_client()
            return
        else
            return
        end
    end
    local next_byte, err, last_byte = client:send(output, sent)
    sent = (next_byte or last_byte or sent - 1) + 1
    if sent > #output or (err and err ~= 'timeout') then close_client() end
end

DCS.setUserCallbacks({
    onSimulationFrame = function()
        local ok, err = pcall(frame)
        if not ok then
            log.write('FoW', log.ERROR, 'bridge frame: ' .. tostring(err))
            close_client()
        end
    end,
    onSimulationStop = close_client,
})
log.write('FoW', log.INFO, 'JSON bridge listening on 10309')
