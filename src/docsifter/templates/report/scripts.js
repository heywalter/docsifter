let currentFalsePositiveData = null;

document.addEventListener('click', function(event) {
    const button = event.target.closest('.false-positive-btn[data-fp-action]');
    if (!button) return;

    const rowId = button.dataset.rowId;
    const original = button.dataset.original;
    const corrected = button.dataset.corrected;
    if (button.dataset.fpAction === 'unmark') {
        unmarkFalsePositive(rowId, original, corrected);
    } else {
        markAsFalsePositive(rowId, original, corrected);
    }
});

function markAsFalsePositive(rowId, original, corrected) {
    currentFalsePositiveData = {
        rowId: rowId,
        original: original,
        corrected: corrected
    };
    const modal = document.getElementById('falsePositiveModal');
    modal.classList.add('show');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    const modal = document.getElementById('falsePositiveModal');
    modal.classList.remove('show');
    document.body.style.overflow = '';
    currentFalsePositiveData = null;
}

function confirmFalsePositive() {
    if (!currentFalsePositiveData) return;

    const isPattern = document.getElementById('isPattern').checked;
    const data = {
        original: currentFalsePositiveData.original,
        corrected: currentFalsePositiveData.corrected,
        is_pattern: isPattern
    };

    fetch('/api/false_positives', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-DocSifter-Request': '1',
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            const row = document.getElementById(currentFalsePositiveData.rowId);
            row.classList.add('false-positive-row');

            const btn = row.querySelector('.false-positive-btn');
            if (btn) {
                btn.textContent = 'Unmark false positive';
                btn.classList.add('marked');
                btn.dataset.fpAction = 'unmark';
            }

            closeModal();
            updateVisibleChanges();
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Failed to mark as false positive, please retry');
    });
}

function unmarkFalsePositive(rowId, original, corrected) {
    fetch('/api/false_positives', {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
            'X-DocSifter-Request': '1',
        },
        body: JSON.stringify({
            original: original,
            corrected: corrected
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            const row = document.getElementById(rowId);
            if (row) {
                row.classList.remove('false-positive-row');

                const btn = row.querySelector('.false-positive-btn');
                if (btn) {
                    btn.textContent = 'Mark as false positive';
                    btn.classList.remove('marked');
                    btn.dataset.fpAction = 'mark';
                }
            }

            updateVisibleChanges();
            alert('False positive removed');
        } else {
            alert('Failed to remove: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Failed to remove false positive, please retry');
    });
}

function toggleDifferences() {
    document.body.classList.toggle('hide-differences');
    const btn = document.querySelectorAll('.toggle-btn')[0];
    btn.classList.toggle('active');
    
    const isHidden = document.body.classList.contains('hide-differences');
    btn.innerHTML = isHidden ?
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3h5v5"/><path d="M8 21H3v-5"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/></svg>Show diffs' :
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3h5v5"/><path d="M8 21H3v-5"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/></svg>Hide diffs';
}

function toggleWhitespace() {
    document.body.classList.toggle('hide-whitespace');
    const btn = document.querySelectorAll('.toggle-btn')[1];
    btn.classList.toggle('active');

    const isHidden = document.body.classList.contains('hide-whitespace');
    btn.innerHTML = isHidden ?
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/><path d="M15 3v18"/></svg>Show whitespace' :
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/><path d="M15 3v18"/></svg>Hide whitespace';

    updateVisibleChanges();
}

function toggleFalsePositives() {
    document.body.classList.toggle('hide-false-positives');
    const btn = document.querySelectorAll('.toggle-btn')[2];
    btn.classList.toggle('active');

    const isHidden = document.body.classList.contains('hide-false-positives');
    btn.innerHTML = isHidden ?
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6"/><path d="M9 9l6 6"/></svg>Show false positives' :
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6"/><path d="M9 9l6 6"/></svg>Hide false positives';

    updateVisibleChanges();
}

function updateVisibleChanges() {
    const tables = document.querySelectorAll('.diff-table');
    let totalVisible = 0;
    let totalWhitespace = 0;
    let totalAll = 0;
    const isHidingWhitespace = document.body.classList.contains('hide-whitespace');

    tables.forEach(table => {
        const allRows = table.querySelectorAll('tr:not(:first-child):not(.false-positive-row)');
        const visibleRows = table.querySelectorAll('tr:not(:first-child):not(.hide-whitespace .whitespace-row):not(.false-positive-row)');
        const whitespaceRows = table.querySelectorAll('.whitespace-row:not(.false-positive-row)');
        const fileSection = table.closest('.file-section');
        
        totalVisible += visibleRows.length;
        totalWhitespace += whitespaceRows.length;
        
        if (isHidingWhitespace) {
            totalAll += allRows.length - whitespaceRows.length;
        } else {
            totalAll += allRows.length;
        }

        if (allRows.length > 0 && visibleRows.length === 0) {
            fileSection.style.display = 'none';
        } else {
            fileSection.style.display = 'block';
        }
    });

    document.querySelectorAll('.stat-value').forEach(value => {
        const text = value.textContent;
        if (text.includes('/')) {
            const mainNumber = value.childNodes[0];
            if (mainNumber && mainNumber.nodeType === Node.TEXT_NODE) {
                mainNumber.textContent = totalVisible.toLocaleString();
            }
            const totalSpan = value.querySelector('.stat-total');
            if (totalSpan) {
                totalSpan.textContent = '/' + totalAll.toLocaleString();
            }
        }
    });

    document.querySelectorAll('.stat-note').forEach(highlight => {
        highlight.textContent = `Whitespace issues: ${totalWhitespace.toLocaleString()}`;
    });
}

document.addEventListener('DOMContentLoaded', function() {
    const toggleBtns = document.querySelectorAll('.toggle-btn');
    toggleBtns[0].innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3h5v5"/><path d="M8 21H3v-5"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/></svg>Show diffs';
    toggleBtns[1].innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/><path d="M15 3v18"/></svg>Show whitespace';
    if (toggleBtns[2]) {
        toggleBtns[2].innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6"/><path d="M9 9l6 6"/></svg>Hide false positives';
    }

    document.querySelectorAll('.false-positive-btn').forEach(btn => {
        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6"/><path d="M9 9l6 6"/></svg>Mark as false positive';
        if (window.location.protocol === 'file:') {
            btn.disabled = true;
            btn.title = 'False-positive actions require the DocSifter Web UI';
        }
    });

    document.querySelector('.modal-close').addEventListener('click', closeModal);
    document.getElementById('toggleDifferencesBtn').addEventListener('click', toggleDifferences);
    document.getElementById('toggleWhitespaceBtn').addEventListener('click', toggleWhitespace);
    document.getElementById('toggleFalsePositivesBtn').addEventListener('click', toggleFalsePositives);
    document.getElementById('confirmFalsePositiveBtn').addEventListener('click', confirmFalsePositive);
    document.getElementById('cancelFalsePositiveBtn').addEventListener('click', closeModal);
    document.getElementById('falsePositiveModal').addEventListener('click', function(e) {
        if (e.target === this) closeModal();
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeModal();
    });
});



