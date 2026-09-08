(function(global) {
  var STORAGE_KEY = 'wca-keep-screen-awake';
  var wakeLock = null;
  var wakeRequest = null;

  function readEnabled() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (raw === null) return true;
      return raw === '1' || raw === 'true';
    } catch (e) {
      return true;
    }
  }

  function shouldHoldWakeLock() {
    return readEnabled() && document.visibilityState === 'visible';
  }

  function releaseWakeLock() {
    var cur = wakeLock;
    wakeLock = null;
    if (!cur) return;
    try { cur.release(); } catch (e) {}
  }

  function requestWakeLock() {
    if (!navigator.wakeLock || typeof navigator.wakeLock.request !== 'function') return;
    if (wakeLock || wakeRequest || !shouldHoldWakeLock()) return;
    wakeRequest = navigator.wakeLock.request('screen').then(function(lock) {
      wakeRequest = null;
      wakeLock = lock;
      if (!wakeLock || typeof wakeLock.addEventListener !== 'function') return;
      wakeLock.addEventListener('release', function() {
        wakeLock = null;
        if (shouldHoldWakeLock()) requestWakeLock();
      });
      if (!shouldHoldWakeLock()) releaseWakeLock();
    }).catch(function() {
      wakeRequest = null;
    });
  }

  function syncWakeLock() {
    if (shouldHoldWakeLock()) requestWakeLock();
    else releaseWakeLock();
  }

  document.addEventListener('visibilitychange', syncWakeLock);
  window.addEventListener('pageshow', syncWakeLock);
  window.addEventListener('pagehide', releaseWakeLock);
  window.addEventListener('storage', function(evt) {
    if (!evt.key || evt.key === STORAGE_KEY) syncWakeLock();
  });

  global.WcaScreenWake = {
    key: STORAGE_KEY,
    isEnabled: readEnabled,
    refresh: syncWakeLock,
    release: releaseWakeLock
  };

  syncWakeLock();
})(window);
