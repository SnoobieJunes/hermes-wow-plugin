-- Calendar tab for Guildhall (created 2026-11-11).
-- Purpose: the window's calendar tab. It turns Guildhall.Calendar.events() into
-- one "title @ starts (role n, role n)" line per upcoming event, roles sorted
-- alphabetically, and draws the first eight as FontStrings on the window frame.
-- Invariants: loading this file creates no frames and builds nothing; the tab
-- is built the first time the window shows it, and only then.

local ADDON_NAME, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.CalendarTab = {
    built = false,
    lines = {},
}

-- [2026-11-11 T-020] The tab shows the first eight rows: the window is an
-- overview, not a scroller, so the line list and the FontStrings stay in step.
local MAX_LINES = 8

-- [2026-11-11 T-020] One line per event. The parenthetical lists the "yes" role
-- counts sorted alphabetically; it is omitted when there is nothing to show, so
-- a row never renders an empty pair of brackets.
local function line_for(row)
    local roles = {}
    for role, count in pairs(row.counts) do
        roles[#roles + 1] = role .. " " .. tostring(count)
    end
    table.sort(roles)
    local line = row.title .. " @ " .. tostring(row.starts)
    if #roles > 0 then
        line = line .. " (" .. table.concat(roles, ", ") .. ")"
    end
    return line
end

-- [2026-11-11 T-057] Pooled FontStrings + refresh-on-show, same shape as
-- TabBoard: a one-time snapshot could never show an event created (or a
-- sign-up received) after the tab was first built.
local texts = {}

local function refresh()
    local rows = ns.Calendar.events()
    local lines = {}
    local shown = math.min(#rows, MAX_LINES)
    for i = 1, shown do
        lines[#lines + 1] = line_for(rows[i])
    end
    ns.CalendarTab.lines = lines
    for i = 1, MAX_LINES do
        local text = texts[i]
        if text ~= nil then
            if lines[i] ~= nil then
                text:SetText(lines[i])
                text:Show()
            else
                text:Hide()
            end
        end
    end
end

ns.CalendarTab.refresh = refresh

local function build(frame)
    ns.CalendarTab.built = true
    local font = (ns.Theme and ns.Theme.font) or "GameFontNormal"
    for i = 1, MAX_LINES do
        local text = frame:CreateFontString(nil, "OVERLAY", font)
        text:SetPoint("TOPLEFT", 16, -40 - (i - 1) * 14)
        texts[i] = text
    end
    refresh()
end

-- [2026-11-11 T-020] Registration only: ns.Window owns the frame and calls
-- build(frame) the first time the tab is shown (SPEC-GUILDHALL §9).
if type(ns.Window) == "table" and type(ns.Window.register_tab) == "function" then
    ns.Window.register_tab("calendar", build, refresh)
end

return ns.CalendarTab
