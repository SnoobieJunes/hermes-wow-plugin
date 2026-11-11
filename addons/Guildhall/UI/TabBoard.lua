-- Board tab for Guildhall (created 2026-11-11).
-- Purpose: the window's board tab. It turns Guildhall.Board.rows() into one
-- "author: text" line per visible post, pins marked, and draws the first eight
-- as FontStrings on the window frame.
-- Invariants: loading this file creates no frames and builds nothing; the tab
-- is built the first time the window shows it, and only then.

local ADDON_NAME, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.BoardTab = {
    built = false,
    lines = {},
}

-- [2026-11-11 T-043] The tab shows the first eight rows: the window is a
-- overview, not a scroller, so the line list and the FontStrings stay in step.
local MAX_LINES = 8

local function build(frame)
    ns.BoardTab.built = true
    ns.BoardTab.lines = {}
    local rows = ns.Board.rows()
    local font = (ns.Theme and ns.Theme.font) or "GameFontNormal"
    local shown = math.min(#rows, MAX_LINES)
    for i = 1, shown do
        local row = rows[i]
        local line = row.a .. ": " .. row.text
        if row.pinned then
            line = "[pin] " .. line
        end
        ns.BoardTab.lines[#ns.BoardTab.lines + 1] = line
        local text = frame:CreateFontString(nil, "OVERLAY", font)
        text:SetPoint("TOPLEFT", 16, -40 - (i - 1) * 14)
        text:SetText(line)
    end
end

-- [2026-11-11 T-043] Registration only: ns.Window owns the frame and calls
-- build(frame) the first time the tab is shown (SPEC-GUILDHALL §9).
if type(ns.Window) == "table" and type(ns.Window.register_tab) == "function" then
    ns.Window.register_tab("board", build)
end

return ns.BoardTab
