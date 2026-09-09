(function(){
  // This is a browser-automation signal, not a guarantee that a visitor is human.
  function isAutomated(){
    return window.navigator && window.navigator.webdriver === true;
  }

  function isVisible(){
    return document.visibilityState !== 'hidden' && !document.prerendering;
  }

  window.echoAnalytics = {
    allowed: function(){ return !isAutomated() && isVisible(); },
    whenVisible: function(callback){
      if (isAutomated()) return;
      var done = false;
      function run(){
        if (done || !isVisible() || isAutomated()) return;
        done = true;
        document.removeEventListener('visibilitychange', run);
        document.removeEventListener('prerenderingchange', run);
        callback();
      }
      document.addEventListener('visibilitychange', run);
      document.addEventListener('prerenderingchange', run);
      run();
    }
  };
})();
