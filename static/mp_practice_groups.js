/**
 * Practice groups: pills + combobox (suggested labels + custom: type and Enter to add).
 */
(function () {
  'use strict';

  var activeCombo = null;

  function hideMenu() {
    if (!activeCombo) return;
    var menu = activeCombo._mpgMenu;
    var input = activeCombo._mpgInput;
    if (menu) {
      menu.hidden = true;
      menu.innerHTML = '';
    }
    if (input) input.setAttribute('aria-expanded', 'false');
    activeCombo = null;
  }

  document.addEventListener(
    'mousedown',
    function (e) {
      if (!activeCombo) return;
      if (activeCombo.contains(e.target)) return;
      hideMenu();
    },
    true
  );

  function normalizeAll(raw) {
    if (!Array.isArray(raw)) return [];
    var out = [];
    for (var i = 0; i < raw.length; i++) {
      var s = String(raw[i]).trim();
      if (s) out.push(s);
    }
    return out;
  }

  function getSelectedSet(hiddensEl) {
    var out = new Set();
    hiddensEl.querySelectorAll('input[name="practice_group"]').forEach(function (inp) {
      var v = (inp.value || '').trim();
      if (v) out.add(v);
    });
    return out;
  }

  function filterAvailable(all, selSet, query) {
    var q = String(query || '').trim().toLowerCase();
    var out = [];
    for (var i = 0; i < all.length; i++) {
      var x = all[i];
      if (selSet.has(x)) continue;
      if (!q || x.toLowerCase().indexOf(q) !== -1) out.push(x);
    }
    return out;
  }

  function emitChange(rootEl, hiddensEl) {
    var vals = [];
    hiddensEl.querySelectorAll('input[name="practice_group"]').forEach(function (inp) {
      var v = (inp.value || '').trim();
      if (v) vals.push(v);
    });
    rootEl.dispatchEvent(
      new CustomEvent('mp-practice-groups-change', { bubbles: true, detail: { values: vals } })
    );
  }

  function mpgAttach(rootEl, allLabels) {
    var pillsEl = rootEl.querySelector('.practice-groups-pills');
    var hiddensEl = rootEl.querySelector('.mp-practice-groups-hiddens');
    var combo = rootEl.querySelector('.mp-practice-groups-combo');
    var input = combo && combo.querySelector('.mp-practice-groups-input');
    var menu = combo && combo.querySelector('.mp-practice-groups-menu');
    if (!pillsEl || !hiddensEl || !input || !menu) return;

    var all = allLabels;
    var activeIdx = -1;

    function addPillForHidden(hidden) {
      var label = (hidden.value || '').trim();
      if (!label) return;
      var span = document.createElement('span');
      span.className = 'practice-group-pill';
      span.setAttribute('role', 'listitem');
      var labEl = document.createElement('span');
      labEl.className = 'practice-group-pill-label';
      labEl.textContent = label;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'practice-group-pill-remove';
      btn.setAttribute('aria-label', 'Remove ' + label);
      btn.innerHTML = '&times;';
      btn.addEventListener('click', function () {
        hidden.remove();
        span.remove();
        if (activeCombo === combo) renderMenu();
        emitChange(rootEl, hiddensEl);
      });
      span.appendChild(labEl);
      span.appendChild(btn);
      pillsEl.appendChild(span);
    }

    function initFromHiddens() {
      pillsEl.innerHTML = '';
      hiddensEl.querySelectorAll('input[name="practice_group"]').forEach(addPillForHidden);
    }

    function pickLabel(text, refocusInput) {
      var t = String(text || '').trim();
      if (!t || getSelectedSet(hiddensEl).has(t)) return;
      rootEl._mpgSkipOpen = true;
      var hid = document.createElement('input');
      hid.type = 'hidden';
      hid.name = 'practice_group';
      hid.value = t;
      hiddensEl.appendChild(hid);
      addPillForHidden(hid);
      input.value = '';
      hideMenu();
      if (refocusInput !== false) input.focus();
      emitChange(rootEl, hiddensEl);
      setTimeout(function () {
        rootEl._mpgSkipOpen = false;
      }, 0);
    }

    function updateActive(opts) {
      opts = opts || menu.querySelectorAll('li');
      for (var i = 0; i < opts.length; i++) {
        opts[i].classList.toggle('mp-suggest-active', i === activeIdx);
      }
    }

    function renderMenu() {
      var sel = getSelectedSet(hiddensEl);
      var filtered = filterAvailable(all, sel, input.value);
      menu.innerHTML = '';
      filtered.forEach(function (text) {
        var li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.className = 'mp-suggest-item';
        li.textContent = text;
        li.dataset.value = text;
        li.addEventListener('mousedown', function (e) {
          e.preventDefault();
          pickLabel(text);
        });
        menu.appendChild(li);
      });
      var opts = menu.querySelectorAll('li');
      activeIdx = -1;
      updateActive(opts);

      if (opts.length === 0) {
        menu.hidden = true;
        input.setAttribute('aria-expanded', 'false');
      } else {
        menu.hidden = false;
        input.setAttribute('aria-expanded', 'true');
      }
    }

    function showMenu() {
      activeCombo = combo;
      combo._mpgInput = input;
      combo._mpgMenu = menu;
      renderMenu();
    }

    initFromHiddens();

    input.addEventListener('focus', function () {
      if (rootEl._mpgSkipOpen) return;
      showMenu();
    });

    input.addEventListener('click', function () {
      if (rootEl._mpgSkipOpen) return;
      showMenu();
    });

    input.addEventListener('input', function () {
      if (rootEl._mpgSkipOpen) return;
      if (activeCombo === combo) renderMenu();
      else showMenu();
    });

    input.addEventListener('blur', function () {
      setTimeout(function () {
        if (document.activeElement === input) return;
        if (activeCombo === combo) hideMenu();
      }, 200);
    });

    input.addEventListener('keydown', function (e) {
      var opts = menu.querySelectorAll('li');
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (!menu.hidden && opts.length) {
          if (activeIdx < 0) activeIdx = 0;
          else activeIdx = Math.min(activeIdx + 1, opts.length - 1);
          updateActive(opts);
        } else {
          showMenu();
        }
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (!menu.hidden && opts.length) {
          if (activeIdx <= 0) activeIdx = -1;
          else activeIdx = activeIdx - 1;
          updateActive(opts);
        } else {
          showMenu();
        }
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        if (!menu.hidden && activeIdx >= 0 && opts[activeIdx]) {
          pickLabel(opts[activeIdx].dataset.value);
        } else {
          var typed = String(input.value || '').trim();
          if (typed) {
            pickLabel(typed);
          } else {
            hideMenu();
          }
        }
        return;
      }
      if (e.key === 'Tab') {
        if (menu.hidden) return;
        if (activeIdx >= 0 && opts[activeIdx]) pickLabel(opts[activeIdx].dataset.value, false);
        else hideMenu();
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        hideMenu();
      }
    });
  }

  /**
   * @param {Element} [root]
   */
  window.mpPracticeGroupsInitScope = function (root) {
    root = root || document;
    root.querySelectorAll('.mp-practice-groups').forEach(function (el) {
      if (el.dataset.mpPracticeGroupsBound === '1') return;
      var script = el.querySelector('script.mp-practice-groups-all[type="application/json"]');
      var items = [];
      if (script) {
        try {
          items = JSON.parse(script.textContent || '[]');
        } catch (err) {
          items = [];
        }
      }
      items = normalizeAll(items);
      mpgAttach(el, items);
      el.dataset.mpPracticeGroupsBound = '1';
    });
  };

  function runInit() {
    window.mpPracticeGroupsInitScope(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runInit);
  } else {
    runInit();
  }
})();
