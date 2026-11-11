-- Safe codec for Guildhall (created 2026-11-11).
-- Purpose: turn plain tables into text and back without executing the text.
-- Invariants:
-- - encode never emits byte 0.
-- - decode of hostile input returns nil plus a message and does not raise.
-- - received text is parsed by this file. It is never executed.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

local HEX = "0123456789ABCDEF"

local function hex_byte(n)
    local hi = math.floor(n / 16)
    local lo = n - hi * 16
    return HEX:sub(hi + 1, hi + 1) .. HEX:sub(lo + 1, lo + 1)
end

local function u32_hex(n)
    n = math.floor(n) % 4294967296
    local out = {}
    for i = 8, 1, -1 do
        local div = 16 ^ (i - 1)
        local digit = math.floor(n / div) % 16
        out[#out + 1] = HEX:sub(digit + 1, digit + 1)
    end
    return table.concat(out)
end

local function hex_to_u32(text)
    local n = 0
    for i = 1, #text do
        local c = HEX:find(text:sub(i, i), 1, true)
        if c == nil then
            return nil
        end
        n = n * 16 + (c - 1)
    end
    return n
end

local function pack_double(sign, biased, frac)
    local frac_hi = math.floor(frac / 4294967296)
    local frac_lo = frac - frac_hi * 4294967296
    local hi = sign * 2147483648 + biased * 1048576 + frac_hi
    return u32_hex(hi) .. u32_hex(frac_lo)
end

local function encode_double(n)
    if n ~= n then
        return nil, "nan is not codec data"
    end
    local sign = 0
    if n < 0 or (n == 0 and 1 / n < 0) then
        sign = 1
        n = -n
    end
    if n == math.huge then
        return pack_double(sign, 2047, 0)
    end
    if n == 0 then
        return pack_double(sign, 0, 0)
    end
    local mant, exp = math.frexp(n)
    local biased = exp - 1 + 1023
    if biased >= 2047 then
        return pack_double(sign, 2047, 0)
    end
    if biased <= 0 then
        local frac = math.floor(n / 2 ^ (-1022) * 2 ^ 52 + 0.5)
        if frac < 0 then
            frac = 0
        end
        if frac > 4503599627370495 then
            frac = 4503599627370495
        end
        return pack_double(sign, 0, frac)
    end
    local frac_unit = mant * 2 - 1
    local frac = math.floor(frac_unit * 4503599627370496 + 0.5)
    if frac >= 4503599627370496 then
        frac = 0
        biased = biased + 1
        if biased >= 2047 then
            return pack_double(sign, 2047, 0)
        end
    end
    return pack_double(sign, biased, frac)
end

local function decode_double(text)
    if #text ~= 16 then
        return nil, "bad float width"
    end
    local hi = hex_to_u32(text:sub(1, 8))
    local lo = hex_to_u32(text:sub(9, 16))
    if hi == nil or lo == nil then
        return nil, "bad float digits"
    end
    local sign = math.floor(hi / 2147483648)
    local biased = math.floor(hi / 1048576) % 2048
    local frac_hi = hi % 1048576
    local frac = frac_hi * 4294967296 + lo
    local magnitude
    if biased == 2047 then
        if frac ~= 0 then
            return nil, "nan is not codec data"
        end
        magnitude = math.huge
    elseif biased == 0 then
        magnitude = frac / 4503599627370496 * 2 ^ (-1022)
    else
        magnitude = (1 + frac / 4503599627370496) * 2 ^ (biased - 1023)
    end
    if sign == 1 then
        magnitude = -magnitude
    end
    return magnitude
end

local function encode_string(value)
    local parts = { "S", tostring(#value), ":" }
    for i = 1, #value do
        local byte = string.byte(value, i)
        if byte == 0 then
            return nil, "string contains byte 0"
        end
        parts[#parts + 1] = hex_byte(byte)
    end
    return table.concat(parts)
end

local function encode_value(value, depth)
    if depth > 32 then
        return nil, "table nested too deep"
    end
    local kind = type(value)
    if kind == "boolean" then
        return value and "T" or "F"
    end
    if kind == "number" then
        if value == math.floor(value) and value > -9007199254740992 and value < 9007199254740992 then
            return "I" .. string.format("%.0f", value) .. ";"
        end
        local hex, err = encode_double(value)
        if hex == nil then
            return nil, err
        end
        return "H" .. hex .. ";"
    end
    if kind == "string" then
        return encode_string(value)
    end
    if kind ~= "table" then
        return nil, "unsupported type " .. kind
    end
    local keys = {}
    for key in pairs(value) do
        if type(key) ~= "string" and type(key) ~= "number" then
            return nil, "unsupported key type " .. type(key)
        end
        keys[#keys + 1] = key
    end
    table.sort(keys, function(a, b)
        return tostring(a) < tostring(b)
    end)
    local parts = { "{", tostring(#keys) }
    for i = 1, #keys do
        local key = keys[i]
        local key_text = type(key) == "number" and ("#" .. string.format("%.0f", key)) or key
        local encoded_key, key_err = encode_string(key_text)
        if encoded_key == nil then
            return nil, key_err
        end
        local encoded, err = encode_value(value[key], depth + 1)
        if encoded == nil then
            return nil, err
        end
        parts[#parts + 1] = encoded_key
        parts[#parts + 1] = encoded
    end
    parts[#parts + 1] = "}"
    return table.concat(parts)
end

local Parser = {}
Parser.__index = Parser

function Parser.new(text)
    return setmetatable({ text = text, i = 1 }, Parser)
end

function Parser:peek()
    return self.text:sub(self.i, self.i)
end

function Parser:take(n)
    local chunk = self.text:sub(self.i, self.i + n - 1)
    if #chunk ~= n then
        return nil, "truncated"
    end
    self.i = self.i + n
    return chunk
end

function Parser:parse()
    local value, err = self:value()
    if err ~= nil then
        return nil, err
    end
    if self.i <= #self.text then
        return nil, "trailing junk"
    end
    return value
end

function Parser:value()
    local tag = self:peek()
    if tag == "T" then
        self.i = self.i + 1
        return true
    end
    if tag == "F" then
        self.i = self.i + 1
        return false
    end
    if tag == "I" then
        return self:integer()
    end
    if tag == "H" then
        return self:float()
    end
    if tag == "S" then
        return self:str()
    end
    if tag == "{" then
        return self:table_value()
    end
    return nil, "bad tag"
end

function Parser:integer()
    self.i = self.i + 1
    local start = self.i
    if self:peek() == "-" then
        self.i = self.i + 1
    end
    local digits = 0
    while self:peek():match("%d") do
        self.i = self.i + 1
        digits = digits + 1
        if digits > 16 then
            return nil, "integer too long"
        end
    end
    if digits == 0 or self:peek() ~= ";" then
        return nil, "bad integer"
    end
    local text = self.text:sub(start, self.i - 1)
    self.i = self.i + 1
    return tonumber(text)
end

function Parser:float()
    self.i = self.i + 1
    local hex, err = self:take(16)
    if hex == nil then
        return nil, err
    end
    if self:peek() ~= ";" then
        return nil, "bad float"
    end
    self.i = self.i + 1
    return decode_double(hex)
end

function Parser:str()
    self.i = self.i + 1
    local start = self.i
    local digits = 0
    while self:peek():match("%d") do
        self.i = self.i + 1
        digits = digits + 1
        if digits > 8 then
            return nil, "string length too long"
        end
    end
    if digits == 0 or self:peek() ~= ":" then
        return nil, "bad string"
    end
    local length = tonumber(self.text:sub(start, self.i - 1))
    self.i = self.i + 1
    local hex, err = self:take(length * 2)
    if hex == nil then
        return nil, err
    end
    local chars = {}
    for i = 1, length do
        local byte = hex_to_u32(hex:sub(i * 2 - 1, i * 2))
        if byte == nil or byte < 1 or byte > 255 then
            return nil, "bad string byte"
        end
        chars[#chars + 1] = string.char(byte)
    end
    return table.concat(chars)
end

function Parser:table_value()
    self.i = self.i + 1
    local start = self.i
    local digits = 0
    while self:peek():match("%d") do
        self.i = self.i + 1
        digits = digits + 1
        if digits > 6 then
            return nil, "table too wide"
        end
    end
    if digits == 0 then
        return nil, "bad table"
    end
    local count = tonumber(self.text:sub(start, self.i - 1))
    local out = {}
    for _ = 1, count do
        local key, key_err = self:str()
        if key == nil then
            return nil, key_err or "bad key"
        end
        local value, err = self:value()
        if err ~= nil then
            return nil, err
        end
        if key:sub(1, 1) == "#" and tonumber(key:sub(2)) ~= nil then
            out[tonumber(key:sub(2))] = value
        else
            out[key] = value
        end
    end
    if self:peek() ~= "}" then
        return nil, "unclosed table"
    end
    self.i = self.i + 1
    return out
end

local function decode(text)
    if type(text) ~= "string" then
        return nil, "expected a string"
    end
    if text:find("\0", 1, true) then
        return nil, "encoded text contains byte 0"
    end
    local ok, value, err = pcall(function()
        return Parser.new(text):parse()
    end)
    if not ok then
        return nil, "rejected: " .. tostring(value)
    end
    if err ~= nil then
        return nil, err
    end
    return value
end

local function encode(value)
    local text, err = encode_value(value, 0)
    if text == nil then
        return nil, err
    end
    if text:find("\0", 1, true) then
        return nil, "encoder emitted byte 0"
    end
    return text
end

ns.Codec = { encode = encode, decode = decode }
return ns.Codec
