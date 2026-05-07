/**
 * Firebase Cloud Messaging Service Worker
 * Served at: /firebase-messaging-sw.js (root scope via Odoo controller)
 */

importScripts('https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.12.0/firebase-messaging-compat.js');

let firebaseConfig = null;
let messaging = null;
let isInitialized = false;

function initFirebase(config) {
    if (isInitialized) return;
    try {
        if (!firebase.apps.length) {
            firebase.initializeApp(config);
        }
        messaging = firebase.messaging();
        isInitialized = true;
        console.log('[FCM SW] Firebase initialized.');

        messaging.onBackgroundMessage((payload) => {
            console.log('[FCM SW] onBackgroundMessage:', payload);
            const { title, body } = payload.notification || {};
            const notificationTitle = title || 'Thong bao';
            const notificationOptions = {
                body: body || '',
                icon: '/web/static/img/favicon.ico',
                badge: '/web/static/img/favicon.ico',
                data: payload.data || {},
                tag: 'motcua-bg-notification',
                requireInteraction: false,
            };
            return self.registration.showNotification(notificationTitle, notificationOptions);
        });
    } catch (e) {
        console.error('[FCM SW] Init error:', e);
    }
}

// Fetch config from server when SW starts independently (no postMessage yet)
async function fetchAndInitFirebase() {
    if (isInitialized) return;
    try {
        const resp = await fetch('/api/web/fcm/config');
        const data = await resp.json();
        if (data.success && data.configured && data.config) {
            firebaseConfig = data.config;
            initFirebase(firebaseConfig);
        }
    } catch (e) {
        console.warn('[FCM SW] Cannot fetch config from server:', e);
    }
}

// Lifecycle
self.addEventListener('install', (event) => {
    console.log('[FCM SW] Installed.');
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    console.log('[FCM SW] Activated.');
    event.waitUntil(clients.claim());
});

// Single message handler
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'FIREBASE_CONFIG') {
        firebaseConfig = event.data.config;
        console.log('[FCM SW] Received Firebase config from main thread.');
        initFirebase(firebaseConfig);
    }
});

// Push fallback when Firebase SDK not ready
self.addEventListener('push', (event) => {
    event.waitUntil(
        (async () => {
            if (!isInitialized) {
                await fetchAndInitFirebase();
            }
            // If still not initialized, show notification manually
            if (!isInitialized) {
                let data = {};
                try {
                    data = event.data ? event.data.json() : {};
                } catch (e) {
                    data = { notification: { title: 'New notification', body: '' } };
                }
                const notification = data.notification || {};
                await self.registration.showNotification(
                    notification.title || 'Thong bao',
                    {
                        body: notification.body || '',
                        icon: '/web/static/img/favicon.ico',
                        data: data.data || {},
                        tag: 'motcua-notification',
                    }
                );
            }
        })()
    );
});

// Click notification
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const notifyData = event.notification.data || {};
    const notifyType = notifyData.type || '';
    const notifyId = notifyData.id || '';

    let url = '/web';
    if (notifyType === 'request' && notifyId) {
        url = `/web#action=service_request&id=${notifyId}`;
    } else if (notifyType === 'notification' && notifyId) {
        url = `/web#action=notification&id=${notifyId}`;
    }

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if (client.url.includes('/web') && 'focus' in client) {
                    client.postMessage({ type: 'NOTIFICATION_CLICK', data: notifyData });
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(url);
            }
        })
    );
});
