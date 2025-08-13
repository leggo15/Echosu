// Edit Tags page JS extracted from inline script
document.addEventListener('DOMContentLoaded', function () {
  const descriptionFields = document.querySelectorAll('.tag-description');
  const messageArea = document.getElementById('message-area');
  const loadingSpinner = document.getElementById('loading-spinner');
  const debounceTimeout = 3000; // 3 seconds
  const debounceTimers = {};

  function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content');
    const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
    return csrfInput ? csrfInput.value : '';
  }
  function showLoading() { loadingSpinner.style.display = 'block'; }
  function hideLoading() { loadingSpinner.style.display = 'none'; }
  function showMessage(message, type) {
    messageArea.innerHTML = `<p class="${type}">${message}</p>`;
    setTimeout(() => { messageArea.innerHTML = ''; }, type === 'success' ? 3000 : 5000);
  }

  descriptionFields.forEach(function(field) {
    field.addEventListener('input', function() {
      const tagId = field.getAttribute('data-tag-id');
      const newDescription = field.value.trim();
      if (debounceTimers[tagId]) clearTimeout(debounceTimers[tagId]);
      debounceTimers[tagId] = setTimeout(function() {
        showLoading();
        fetch(window.editTagsPage?.editUrl || '', {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': getCSRFToken(), 'X-Requested-With': 'XMLHttpRequest' },
          body: new URLSearchParams({ 'tag_id': tagId, 'description': newDescription })
        })
        .then(r => r.json())
        .then(data => {
          if (data.status === 'success') {
            showMessage(`${data.message} Author: ${data.description_author}`, 'success');
            const authorCell = field.closest('tr').querySelector('td:nth-child(4)');
            authorCell.textContent = data.description_author;
            const voteSection = field.closest('td').querySelector('.vote-section');
            voteSection.querySelector('.upvote-count').textContent = data.upvotes;
            voteSection.querySelector('.downvote-count').textContent = data.downvotes;
            voteSection.querySelector('.upvote-btn').disabled = false;
            voteSection.querySelector('.downvote-btn').disabled = false;
            voteSection.querySelector('.upvote-btn').classList.remove('disabled-btn');
            voteSection.querySelector('.downvote-btn').classList.remove('disabled-btn');
            voteSection.querySelector('.upvote-btn').style.backgroundColor = '';
            voteSection.querySelector('.downvote-btn').style.backgroundColor = '';
          } else { showMessage(data.message, 'error'); }
        })
        .catch(() => showMessage('An error occurred while updating the description.', 'error'))
        .finally(() => { hideLoading(); delete debounceTimers[tagId]; });
      }, debounceTimeout);
    });
  });

  const voteSections = document.querySelectorAll('.vote-section');
  voteSections.forEach(function(voteSection) {
    const tagId = voteSection.getAttribute('data-tag-id');
    const upvoteBtn = voteSection.querySelector('.upvote-btn');
    const downvoteBtn = voteSection.querySelector('.downvote-btn');
    const upvoteCountSpan = voteSection.querySelector('.upvote-count');
    const downvoteCountSpan = voteSection.querySelector('.downvote-count');
    function handleVote(voteType) {
      const csrfToken = getCSRFToken();
      showLoading();
      fetch(window.editTagsPage?.voteUrl || '', {
        method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken, 'X-Requested-With': 'XMLHttpRequest' },
        body: new URLSearchParams({ 'tag_id': tagId, 'vote_type': voteType })
      })
      .then(r => r.json())
      .then(data => {
        if (data.status === 'success') {
          upvoteCountSpan.textContent = data.upvotes; downvoteCountSpan.textContent = data.downvotes;
          upvoteBtn.disabled = false; downvoteBtn.disabled = false; upvoteBtn.style.backgroundColor = ''; downvoteBtn.style.backgroundColor = '';
          upvoteBtn.classList.remove('disabled-btn'); downvoteBtn.classList.remove('disabled-btn');
          if (data.removed) { showMessage('Your vote has been removed.', 'success'); }
          else if (data.changed) { if (voteType === 'upvote') { upvoteBtn.style.backgroundColor = 'green'; } else { downvoteBtn.style.backgroundColor = 'red'; } showMessage('Your vote has been updated.', 'success'); }
          else if (data.new_vote) { if (voteType === 'upvote') { upvoteBtn.style.backgroundColor = 'green'; } else { downvoteBtn.style.backgroundColor = 'red'; } showMessage('Your vote has been recorded.', 'success'); }
          if (data.new_vote || data.changed) { if (voteType === 'upvote') { downvoteBtn.disabled = true; downvoteBtn.classList.add('disabled-btn'); } else { upvoteBtn.disabled = true; upvoteBtn.classList.add('disabled-btn'); } }
          if (data.is_locked) { const desc = document.querySelector(`.tag-description[data-tag-id="${tagId}"]`); desc.disabled = true; showMessage(`Description for tag "${data.tag_name}" has been locked due to high vote score.`, 'success'); }
        } else { showMessage(data.message, 'error'); }
      })
      .catch(() => showMessage('An error occurred while voting.', 'error'))
      .finally(() => hideLoading());
    }
    upvoteBtn.addEventListener('click', function(){ handleVote('upvote'); });
    downvoteBtn.addEventListener('click', function(){ handleVote('downvote'); });
  });
});

