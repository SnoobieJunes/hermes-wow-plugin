-- Marks tab for Guildhall (created 2026-11-11).
-- Purpose: the window's marks tab. It turns Guildhall.Marks.leaderboard() into one
-- "who: balance" line per ranked member plus a trailing "pending: N" line, and
-- draws the first eight lines as FontStrings on the window frame.
-- Invariants: loading this file creates no frames and builds nothing; the tab
-- is built the first time the window shows it, and only then.

local ADDON_NAME, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.MarksTab = {
    built = false,
    lines = {},
}

-- [2026-11-11 T-021] The tab shows the first eight lines: the window is an
-- overview, not a scroller, so the line list and the FontStrings stay in step.
local MAX_LINES = 8

-- [2026-11-11 T-057] Pooled FontStrings + refresh-on-show, same shape as
-- TabBoard: balances move whenever a claim lands, so a first-build snapshot
-- is stale the moment the guild plays.
local texts = {}

local function refresh()
    local rows = ns.Marks.leaderboard()
    -- [2026-11-11 T-021] The pending count trails the ranked rows, so an empty
    -- ledger still renders the officer's queue length (SPEC-GUILDHALL §7).
    -- pending() returns the queue rows, so the count is its length.
    local lines = {}
    local shown = math.min(#rows, MAX_LINES)
    for i = 1, shown do
        local row = rows[i]
        lines[#lines + 1] = row.who .. ": " .. tostring(row.balance)
    end
    lines[#lines + 1] = "pending: " .. tostring(#ns.Marks.pending())
    ns.MarksTab.lines = lines
    -- [2026-11-11 T-021] The line list is the source of truth for the drawn
    -- FontStrings, so the two can never disagree on what the tab shows.
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

ns.MarksTab.refresh = refresh

local function build(frame)
    ns.MarksTab.built = true
    local font = (ns.Theme and ns.Theme.font) or "GameFontNormal"
    for i = 1, MAX_LINES do
        local text = frame:CreateFontString(nil, "OVERLAY", font)
        text:SetPoint("TOPLEFT", 16, -40 - (i - 1) * 14)
        texts[i] = text
    end
    refresh()
end

-- [2026-11-11 T-021] Registration only: ns.Window owns the frame and calls
-- build(frame) the first time the tab is shown (SPEC-GUILDHALL §9).
if type(ns.Window) == "table" and type(ns.Window.register_tab) == "function" then
    ns.Window.register_tab("marks", build, refresh)
end

return ns.MarksTab
