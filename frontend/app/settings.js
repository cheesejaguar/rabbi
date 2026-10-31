/**
 * Settings: profile (denomination + bio), credits, data export, and account
 * deletion with a typed confirmation.
 */
import { $, showScreen } from './dom.js';
import { state } from './store.js';
import { api } from './api.js';
import { announce, openModal, closeModal, closeOnBackdrop } from './a11y.js';
import { showToast } from './toast.js';
import { fullName } from './auth.js';
import { loadCredits } from './payments.js';
import { closeDrawer } from './sidebar.js';

let returnScreen = 'welcomeScreen';

export async function showSettings() {
    const visible = document.body.dataset.screen;
    if (visible && visible !== 'settingsScreen') returnScreen = visible;
    showScreen('settingsScreen');
    closeDrawer();
    if (state.user) {
        const name = $('settingsUserName');
        const email = $('settingsUserEmail');
        name.textContent = fullName(state.user);
        email.textContent = state.user.email || '-';
        name.classList.remove('skeleton', 'settings-value-skeleton');
        email.classList.remove('skeleton', 'settings-value-skeleton');
    }
    $('settingsTitle').focus({ preventScroll: true });
    await Promise.all([loadCredits(), loadProfile()]);
}

export function hideSettings() {
    showScreen(returnScreen === 'chatScreen' && !$('chatMessages').childElementCount ? 'welcomeScreen' : returnScreen);
}

const updateBioCount = () => { $('bioCharCount').textContent = String($('bioInput').value.length); };

async function loadProfile() {
    try {
        const data = await api.get('/profile');
        $('denominationSelect').value = data.denomination || '';
        $('bioInput').value = data.bio || '';
        updateBioCount();
    } catch (error) {
        console.warn('Failed to load profile:', error);
    }
}

async function saveProfile() {
    const button = $('saveProfileBtn');
    const original = button.innerHTML;
    button.disabled = true;
    button.textContent = 'Saving…';
    try {
        await api.put('/profile', {
            denomination: $('denominationSelect').value || null,
            bio: $('bioInput').value || null,
        });
        button.textContent = 'Saved';
        announce('Profile saved successfully.');
        setTimeout(() => { button.innerHTML = original; button.disabled = false; }, 1800);
    } catch (error) {
        showToast(error.message || 'Failed to save profile', { tone: 'error' });
        announce('Profile could not be saved.');
        button.innerHTML = original;
        button.disabled = false;
    }
}

async function exportData() {
    const button = $('exportDataBtn');
    button.disabled = true;
    try {
        const response = await fetch('/api/account/export', { credentials: 'include' });
        if (!response.ok) throw new Error(`Export failed (${response.status})`);
        const blob = await response.blob();
        const disposition = response.headers.get('content-disposition') || '';
        const match = /filename="?([^";]+)"?/i.exec(disposition);
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = match ? match[1] : `rebbe-dev-export-${new Date().toISOString().slice(0, 10)}.json`;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
        announce('Your data download has started.');
    } catch (error) {
        console.warn(error);
        showToast('Could not prepare your data. Please try again.', { tone: 'error' });
    } finally {
        button.disabled = false;
    }
}

function openDeleteDialog() {
    const input = $('deleteAccountConfirm');
    input.value = '';
    $('confirmDeleteAccount').disabled = true;
    $('deleteAccountError').classList.add('hidden');
    openModal($('deleteAccountModal'), { onClose: closeDeleteDialog, initialFocus: input });
}

const closeDeleteDialog = () => closeModal($('deleteAccountModal'));

async function confirmDelete() {
    const button = $('confirmDeleteAccount');
    if ($('deleteAccountConfirm').value.trim() !== 'DELETE') return;
    button.disabled = true;
    button.textContent = 'Deleting…';
    try {
        await api.del('/account', { confirm: 'DELETE' });
        window.location.href = '/';
    } catch (error) {
        const errorEl = $('deleteAccountError');
        errorEl.textContent = error.message || 'Your account could not be deleted. Please try again.';
        errorEl.classList.remove('hidden');
        button.textContent = 'Delete account';
        button.disabled = false;
    }
}

export function initSettings() {
    $('settingsBackBtn').addEventListener('click', hideSettings);
    $('bioInput').addEventListener('input', updateBioCount);
    $('saveProfileBtn').addEventListener('click', saveProfile);
    $('exportDataBtn').addEventListener('click', exportData);
    $('deleteAccountBtn').addEventListener('click', openDeleteDialog);
    $('closeDeleteAccount').addEventListener('click', closeDeleteDialog);
    $('cancelDeleteAccount').addEventListener('click', closeDeleteDialog);
    closeOnBackdrop($('deleteAccountModal'), closeDeleteDialog);
    $('deleteAccountConfirm').addEventListener('input', (event) => {
        $('confirmDeleteAccount').disabled = event.target.value.trim() !== 'DELETE';
    });
    $('deleteAccountConfirm').addEventListener('keydown', (event) => {
        if (event.key === 'Enter') confirmDelete();
    });
    $('confirmDeleteAccount').addEventListener('click', confirmDelete);
}
