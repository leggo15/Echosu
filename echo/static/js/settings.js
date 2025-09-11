// Settings page interactions extracted from inline script
$(function(){
  // Collapsibles
  $('.collapsible-header').on('click', function(){
    $(this).toggleClass('active');
    $(this).find('.arrow').toggleClass('rotated');
    $(this).next('.collapsible-content').toggleClass('show');
  });

  // Rename key (dblclick)
  $('.api-key-name').on('dblclick', function(){
    var $current = $(this);
    if ($('.edit-input').length) { alert('Please finish editing the current API key before editing another.'); return; }
    var currentName = $current.text().trim();
    var apiKeyId = $current.data('api-key-id');
    var $input = $('<input>', { type: 'text', 'class': 'edit-input', value: currentName });
    var $save = $('<button>', { type: 'button', 'class': 'save-button', text: 'Save' });
    var $cancel = $('<button>', { type: 'button', 'class': 'cancel-button', text: 'Cancel' });
    $current.hide().after($input, $save, $cancel);
    $input.focus();
    $save.on('click', function(){
      var newName = $input.val().trim();
      if (!newName) { alert('API Key name cannot be empty.'); $input.focus(); return; }
      var $form = $('<form>', { method: 'POST', action: window.settingsPage?.settingsUrl || '' });
      var csrf = window.settingsPage?.csrf || $('input[name=csrfmiddlewaretoken]').val();
      $form.append($('<input>', { type: 'hidden', name: 'csrfmiddlewaretoken', value: csrf }));
      $form.append($('<input>', { type: 'hidden', name: 'api_key_id', value: apiKeyId }));
      $form.append($('<input>', { type: 'hidden', name: 'key_name', value: newName }));
      $('body').append($form); $form.trigger('submit');
    });
    $cancel.on('click', function(){ $input.remove(); $save.remove(); $cancel.remove(); $current.show(); });
    $input.on('keypress', function(e){ if (e.which === 13) { $save.click(); } });
  });

  // Delete API key
  $('.delete-button').on('click', function(){
    var $btn = $(this); var id = $btn.data('api-key-id'); var name = $btn.data('api-key-name');
    if (!confirm('Are you sure you want to delete the API Key "' + name + '"? This action cannot be undone.')) return;
    var $form = $('<form>', { method: 'POST', action: window.settingsPage?.settingsUrl || '' });
    var csrf = window.settingsPage?.csrf || $('input[name=csrfmiddlewaretoken]').val();
    $form.append($('<input>', { type: 'hidden', name: 'csrfmiddlewaretoken', value: csrf }));
    $form.append($('<input>', { type: 'hidden', name: 'delete_key', value: '1' }));
    $form.append($('<input>', { type: 'hidden', name: 'api_key_id', value: id }));
    $('body').append($form); $form.trigger('submit');
  });

  // Delete all data
  $('.delete-data-btn').on('click', function(){
    if (confirm('Are you sure you want to delete all your data? This action cannot be undone.')) {
      window.location.href = window.settingsPage?.confirmUrl || '';
    }
  });

  // -------------------- Auto-save preferences -------------------- //
  function getCsrfToken(){
    try { return window.settingsPage?.csrf || $('input[name=csrfmiddlewaretoken]').first().val(); } catch(e) {}
    return '';
  }
  var saveInFlight = null;
  var saveToastTimer = null;
  function showToast(msg){
    var $t = $('#settingsSaveToast');
    if (!$t.length) {
      $t = $('<div id="settingsSaveToast" class="settings-toast" role="status" aria-live="polite"></div>');
      $('body').append($t);
    }
    $t.text(msg).addClass('show');
    if (saveToastTimer) clearTimeout(saveToastTimer);
    saveToastTimer = setTimeout(function(){ $t.removeClass('show'); }, 1200);
  }
  function postPrefs(data){
    if (saveInFlight) { try { saveInFlight.abort(); } catch(e) {} }
    saveInFlight = $.ajax({
      url: window.settingsPage?.settingsUrl || window.location.href,
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': (function(){ try { return $('input[name=csrfmiddlewaretoken]').first().val() || ''; } catch(e) { return ''; } })() },
      data: Object.assign({ csrfmiddlewaretoken: getCsrfToken() }, data),
    })
    .done(function(resp){ showToast('Saved'); })
    .fail(function(){ showToast('Save failed'); });
  }
  // Debounce for selects
  var debounceTimer = null;
  function debounce(fn){
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(fn, 150);
  }
  // Wire inputs
  $('[data-autosave="checkbox"]').on('change', function(){
    var key = this.name; var checked = this.checked;
    var payload = {}; payload[key] = checked ? '1' : '0';
    postPrefs(payload);
  });
  $('[data-autosave="select"]').on('change', function(){
    var key = this.name; var val = $(this).val();
    debounce(function(){ var payload = {}; payload[key] = val; postPrefs(payload); });
  });
});

