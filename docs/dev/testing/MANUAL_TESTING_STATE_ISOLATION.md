# Manual Testing Procedure: Tabbed Gallery State Isolation

## Overview
This document provides step-by-step manual testing procedures to verify state isolation between tabs in the TabbedGalleryWidget.

## Prerequisites
- ImxUp application running
- Multiple galleries loaded across different tabs
- At least 3 tabs created (Main, Tab1, Tab2)
- Each tab has at least 20-30 galleries for scrolling

---

## Test Suite 1: Scroll Position Independence

### Test 1.1: Basic Scroll Isolation
**Objective**: Verify each tab maintains independent scroll position

**Steps**:
1. Switch to **Tab1**
2. Scroll down to approximately gallery #15
3. Note the current visible gallery name
4. Switch to **Tab2**
5. Verify Tab2 shows galleries from the top (not scrolled)
6. Scroll down to approximately gallery #25 in Tab2
7. Switch back to **Tab1**

**Expected Result**:
- Tab1 should show gallery #15 (where you left it)
- Tab1 scroll position should NOT be affected by Tab2's scroll to #25

**Current Status**: ❌ **FAILING** - Tabs share scroll position

**Pass Criteria**: Each tab preserves its own scroll position independently

---

### Test 1.2: Rapid Tab Switching Scroll Preservation
**Objective**: Verify scroll positions survive rapid tab switching

**Steps**:
1. Set scroll positions:
   - Main tab: Scroll to gallery #10
   - Tab1: Scroll to gallery #20
   - Tab2: Scroll to gallery #30
2. Rapidly switch between tabs 5 times: Main → Tab1 → Tab2 → Tab1 → Main
3. Return to each tab and verify scroll position

**Expected Result**:
- Main tab: Still showing gallery #10
- Tab1: Still showing gallery #20
- Tab2: Still showing gallery #30

**Current Status**: ❌ **FAILING**

---

## Test Suite 2: Selection State Isolation

### Test 2.1: Independent Selection Per Tab
**Objective**: Verify each tab maintains its own selection state

**Steps**:
1. Switch to **Tab1**
2. Select galleries at rows 3, 4, and 5 (Ctrl+Click for multi-select)
3. Note selected gallery names
4. Switch to **Tab2**
5. Verify no galleries are selected in Tab2
6. Select galleries at rows 7 and 8 in Tab2
7. Switch back to **Tab1**

**Expected Result**:
- Tab1 should still have rows 3, 4, 5 selected
- Tab1 selections should NOT be lost when switching to Tab2

**Current Status**: ❌ **FAILING** - Selection is cleared on tab switch

**Pass Criteria**: Each tab remembers which galleries were selected

---

### Test 2.2: Multi-Select Preservation
**Objective**: Verify complex multi-select states are preserved

**Steps**:
1. In Tab1, select multiple non-consecutive galleries:
   - Gallery at row 2
   - Gallery at row 5
   - Gallery at row 8
   - Gallery at row 12
2. Switch to Tab2
3. Select different galleries in Tab2
4. Switch to Main tab
5. Switch back to Tab1

**Expected Result**:
- Tab1 should have exact same 4 galleries selected (rows 2, 5, 8, 12)
- No additional selections or deselections

**Current Status**: ❌ **FAILING**

---

## Test Suite 3: Keyboard Navigation Scope

### Test 3.1: Home Key Scoped to Current Tab
**Objective**: Verify Home key only affects current tab's scroll

**Steps**:
1. Switch to **Main** tab and scroll to middle (gallery #15)
2. Switch to **Tab1** and scroll to bottom
3. While in Tab1, press **Home** key
4. Verify Tab1 scrolls to top
5. Switch to **Main** tab

**Expected Result**:
- Tab1 should be at top after pressing Home
- Main tab should still be at gallery #15 (not affected by Home key in Tab1)

**Current Status**: ⚠️ **UNKNOWN** - Needs testing

**Pass Criteria**: Home key only scrolls the current tab

---

### Test 3.2: End Key Scoped to Current Tab
**Objective**: Verify End key only affects current tab's scroll

**Steps**:
1. Switch to **Main** tab and scroll to top
2. Switch to **Tab1** and scroll to top
3. While in Tab1, press **End** key
4. Verify Tab1 scrolls to bottom
5. Switch to **Main** tab

**Expected Result**:
- Tab1 should be at bottom after pressing End
- Main tab should still be at top (not affected by End key in Tab1)

**Current Status**: ⚠️ **UNKNOWN** - Needs testing

---

### Test 3.3: Page Up/Down Scoped to Current Tab
**Objective**: Verify Page Up/Down only affects current tab

**Steps**:
1. In Main tab, scroll to gallery #20
2. Switch to Tab1, scroll to top
3. Press **Page Down** 3 times in Tab1
4. Switch back to Main tab

**Expected Result**:
- Main tab should still show gallery #20
- Not affected by Page Down in Tab1

**Current Status**: ⚠️ **UNKNOWN**

---

## Test Suite 4: Start Button Deselection Bug

### Test 4.1: Single Gallery Start Preserves Selection
**Objective**: Verify Start button doesn't deselect the gallery

**Steps**:
1. In any tab, select a gallery by clicking on it (row should be highlighted)
2. Click the **Start** button for that gallery
3. Observe the selection state

**Expected Result**:
- Gallery should remain selected (highlighted) after clicking Start
- User should be able to immediately see which gallery they just started

**Current Status**: ❌ **FAILING** - Gallery becomes deselected after Start

**Pass Criteria**: Gallery stays selected after Start button click

---

### Test 4.2: Multi-Select Start Preserves Selection
**Objective**: Verify batch Start operation preserves selection

**Steps**:
1. Select multiple galleries (3-5 galleries)
2. Right-click and choose "Start Selected"
3. Observe selection state

**Expected Result**:
- All started galleries should remain selected
- User can see which galleries are being processed

**Current Status**: ❌ **FAILING**

---

## Test Suite 5: Tab Switching State Preservation

### Test 5.1: Comprehensive State Preservation
**Objective**: Verify ALL state elements are preserved

**Steps**:
1. In **Tab1**:
   - Scroll to gallery #15
   - Select galleries at rows 10, 11, 12
   - Set keyboard focus to row 11 (click on gallery name)
2. In **Tab2**:
   - Scroll to gallery #25
   - Select galleries at rows 20, 21
   - Set keyboard focus to row 20
3. Switch to Main tab
4. Switch back to Tab1

**Expected Result** (Tab1):
- ✅ Scroll position at gallery #15
- ✅ Galleries 10, 11, 12 selected
- ✅ Keyboard focus on row 11

**Current Status**: ❌ **FAILING** - None of the state is preserved

---

### Test 5.2: State Isolation Under Load
**Objective**: Verify state isolation works with many galleries

**Steps**:
1. Load 50+ galleries into each tab
2. In each tab, set unique:
   - Scroll position
   - Selection (3-5 galleries)
   - Current row
3. Perform 10 rapid tab switches
4. Verify each tab's state

**Expected Result**:
- Each tab maintains its unique state
- No state bleeding between tabs

**Current Status**: ❌ **FAILING**

---

## Test Suite 6: Edge Cases

### Test 6.1: Empty Tab State
**Objective**: Verify empty tabs don't cause state corruption

**Steps**:
1. Create a new tab with no galleries
2. Switch between empty tab and populated tabs
3. Verify no crashes or state corruption

**Expected Result**:
- Empty tab displays correctly
- No impact on other tabs' state

**Current Status**: ✅ **PASSING** (Likely working)

---

### Test 6.2: Single Gallery Tab State
**Objective**: Verify single-item tabs work correctly

**Steps**:
1. Create tab with only 1 gallery
2. Select the gallery
3. Switch to another tab and back

**Expected Result**:
- Single gallery remains selected

**Current Status**: ⚠️ **UNKNOWN**

---

## Known Issues Summary

### Critical Issues (P0)
1. **Selection Lost on Tab Switch** - Selecting galleries in one tab and switching to another clears the selection
2. **Scroll Position Not Isolated** - All tabs share the same scroll position
3. **Start Button Deselection** - Clicking Start button deselects the gallery

### High Priority Issues (P1)
4. **Keyboard Navigation Global Scope** - Home/End keys may affect all tabs instead of current tab only
5. **Multi-Select State Lost** - Complex selection patterns are not preserved

### Medium Priority Issues (P2)
6. **Current Row/Focus Lost** - Keyboard focus position not preserved per tab

---

## Implementation Requirements

To fix these issues, TabbedGalleryWidget needs:

1. **Per-Tab State Cache**:
   ```python
   self._tab_states = {
       'tab_name': {
           'scroll_position': int,
           'selected_rows': set[int],
           'current_row': int,
           'horizontal_scroll': int
       }
   }
   ```

2. **State Capture on Tab Switch**:
   - Before switching away from tab, capture all state
   - Store in `_tab_states[old_tab_name]`

3. **State Restoration on Tab Activate**:
   - When switching to tab, restore state from cache
   - Apply scroll position, selection, focus

4. **Start Button Focus Management**:
   - Set `setFocusPolicy(Qt.NoFocus)` on Start buttons
   - Or implement custom event filter to preserve selection

---

## Test Execution Checklist

- [ ] Test 1.1: Basic Scroll Isolation
- [ ] Test 1.2: Rapid Tab Switching Scroll
- [ ] Test 2.1: Independent Selection Per Tab
- [ ] Test 2.2: Multi-Select Preservation
- [ ] Test 3.1: Home Key Scoped
- [ ] Test 3.2: End Key Scoped
- [ ] Test 3.3: Page Up/Down Scoped
- [ ] Test 4.1: Single Gallery Start
- [ ] Test 4.2: Multi-Select Start
- [ ] Test 5.1: Comprehensive State
- [ ] Test 5.2: State Under Load
- [ ] Test 6.1: Empty Tab
- [ ] Test 6.2: Single Gallery Tab

---

## Reporting Results

When testing, record:
- ✅ **PASS** - Feature works as expected
- ❌ **FAIL** - Feature does not work, provide details
- ⚠️ **PARTIAL** - Works sometimes, note conditions
- 🔍 **UNKNOWN** - Unable to test, explain why

For each failure, note:
1. Expected behavior
2. Actual behavior
3. Steps to reproduce
4. Screenshots/video if possible

---

## Automation Status

Automated tests created in:
- `/home/jimbo/imxup/tests/unit/gui/widgets/test_tabbed_state_isolation.py`

Run tests with:
```bash
pytest tests/unit/gui/widgets/test_tabbed_state_isolation.py -v
```

Current automation coverage:
- Scroll position isolation: ✅ Automated
- Selection state isolation: ✅ Automated
- Keyboard navigation scope: ✅ Automated
- Start button deselection: ✅ Automated
- Tab switching preservation: ✅ Automated
- Edge cases: ✅ Automated

---

## References

- Implementation: `/home/jimbo/imxup/src/gui/widgets/tabbed_gallery.py`
- Table Widget: `/home/jimbo/imxup/src/gui/widgets/gallery_table.py`
- Automated Tests: `/home/jimbo/imxup/tests/unit/gui/widgets/test_tabbed_state_isolation.py`
