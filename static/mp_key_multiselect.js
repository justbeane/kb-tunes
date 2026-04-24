/**
 * Key (tune/set): pills + combobox — same behavior as practice groups (mp_practice_groups.js).
 */
(function () {
  'use strict';

  var activeCombo = null;
  var menuRepositionCleanup = null;

  /** Dropdown inside .tune-modal-dialog: use fixed coords so overflow-y:auto on the dialog does not gain a scrollbar. */
  function mpkMenuTuneModalPosition(input, menu) {
    if (!input || !menu || !input.closest('.tune-modal-dialog')) return false;
    var rect = input.getBoundingClientRect();
    var w = Math.max(rect.width, 200);
    var left = Math.max(8, Math.min(rect.left, window.innerWidth - w - 8));
    menu.style.position = 'fixed';
    menu.style.left = left + 'px';
    menu.style.top = rect.bottom + 2 + 'px';
    menu.style.width = w + 'px';
    menu.style.right = 'auto';
    menu.style.bottom = 'auto';
    menu.style.zIndex = '500';
    return true;
  }

  function mpkMenuClearPosition(menu) {
    if (!menu) return;
    menu.style.position = '';
    menu.style.left = '';
    menu.style.top = '';
    menu.style.width = '';
    menu.style.right = '';
    menu.style.bottom = '';
    menu.style.zIndex = '';
  }

  function mpkUnbindMenuReposition() {
    if (typeof menuRepositionCleanup === 'function') {
      menuRepositionCleanup();
      menuRepositionCleanup = null;
    }
  }

  function hideMenu() {
    if (!activeCombo) return;
    var menu = activeCombo._mpkMenu;
    var face = activeCombo._mpkMenuFace || menu;
    var input = activeCombo._mpkInput;
    mpkUnbindMenuReposition();
    if (face) {
      face.hidden = true;
      if (menu) menu.innerHTML = '';
      mpkMenuClearPosition(face);
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
    hiddensEl.querySelectorAll('input[name="key"]').forEach(function (inp) {
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
    hiddensEl.querySelectorAll('input[name="key"]').forEach(function (inp) {
      var v = (inp.value || '').trim();
      if (v) vals.push(v);
    });
    rootEl.dispatchEvent(
      new CustomEvent('mp-key-ms-change', { bubbles: true, detail: { values: vals } })
    );
  }

  function mpkAttach(rootEl, allLabels) {
    var pillsEl = rootEl.querySelector('.practice-groups-pills');
    var hiddensEl = rootEl.querySelector('.mp-key-ms-hiddens');
    var combo = rootEl.querySelector('.mp-key-ms-combo');
    var input = combo && combo.querySelector('.mp-key-ms-input');
    var menu = combo && combo.querySelector('.mp-key-ms-menu');
    if (!pillsEl || !hiddensEl || !input || !menu) return;
    var menuFace = menu.closest('.mp-suggest-menu-shell') || menu;

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
      hiddensEl.querySelectorAll('input[name="key"]').forEach(addPillForHidden);
    }

    function pickLabel(text, refocusInput) {
      var t = String(text || '').trim();
      if (!t || getSelectedSet(hiddensEl).has(t)) return;
      rootEl._mpkSkipOpen = true;
      var hid = document.createElement('input');
      hid.type = 'hidden';
      hid.name = 'key';
      hid.value = t;
      hiddensEl.appendChild(hid);
      addPillForHidden(hid);
      input.value = '';
      hideMenu();
      if (refocusInput !== false) input.focus();
      emitChange(rootEl, hiddensEl);
      setTimeout(function () {
        rootEl._mpkSkipOpen = false;
      }, 0);
    }

    function updateActive(opts) {
      opts = opts || menu.querySelectorAll('li');
      for (var i = 0; i < opts.length; i++) {
        opts[i].classList.toggle('mp-suggest-active', i === activeIdx);
      }
    }

    function mpkBindMenuReposition() {
      mpkUnbindMenuReposition();
      var handler = function () {
        if (activeCombo !== combo || !input || !menuFace || menuFace.hidden) return;
        if (input.closest('.tune-modal-dialog')) mpkMenuTuneModalPosition(input, menuFace);
      };
      window.addEventListener('scroll', handler, true);
      window.addEventListener('resize', handler);
      menuRepositionCleanup = function () {
        window.removeEventListener('scroll', handler, true);
        window.removeEventListener('resize', handler);
      };
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
        menuFace.hidden = true;
        input.setAttribute('aria-expanded', 'false');
        mpkMenuClearPosition(menuFace);
        mpkUnbindMenuReposition();
      } else {
        if (mpkMenuTuneModalPosition(input, menuFace)) mpkBindMenuReposition();
        else {
          mpkMenuClearPosition(menuFace);
          mpkUnbindMenuReposition();
        }
        menuFace.hidden = false;
        input.setAttribute('aria-expanded', 'true');
      }
    }

    function showMenu() {
      activeCombo = combo;
      combo._mpkInput = input;
      combo._mpkMenu = menu;
      combo._mpkMenuFace = menuFace;
      renderMenu();
    }

    initFromHiddens();

    input.addEventListener('focus', function () {
      if (rootEl._mpkSkipOpen) return;
      showMenu();
    });

    input.addEventListener('click', function () {
      if (rootEl._mpkSkipOpen) return;
      showMenu();
    });

    input.addEventListener('input', function () {
      if (rootEl._mpkSkipOpen) return;
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
        if (!menuFace.hidden && opts.length) {
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
        if (!menuFace.hidden && opts.length) {
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
        if (!menuFace.hidden && activeIdx >= 0 && opts[activeIdx]) {
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
        if (menuFace.hidden) return;
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

  window.mpKeyMultiselectInitScope = function (root) {
    root = root || document;
    root.querySelectorAll('.mp-key-ms').forEach(function (el) {
      if (el.dataset.mpKeyMsBound === '1') return;
      var script = el.querySelector('script.mp-key-ms-all[type="application/json"]');
      var items = [];
      if (script) {
        try {
          items = JSON.parse(script.textContent || '[]');
        } catch (err) {
          items = [];
        }
      }
      items = normalizeAll(items);
      mpkAttach(el, items);
      el.dataset.mpKeyMsBound = '1';
    });
  };

  function runInit() {
    window.mpKeyMultiselectInitScope(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runInit);
  } else {
    runInit();
  }
})();
