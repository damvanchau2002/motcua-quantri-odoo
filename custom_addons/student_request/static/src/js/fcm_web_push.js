/** @odoo-module **/

import { session } from "@web/session";
import { registry } from "@web/core/registry";

const FCM_CONFIG_URL = '/api/web/fcm/config';
const FCM_REGISTER_URL = '/api/web/fcm/register';
const FCM_SW_URL = '/firebase-messaging-sw.js';

const FIREBASE_JS_SDK = 'https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js';
const FIREBASE_MESSAGING_SDK = 'https://www.gstatic.com/firebasejs/10.12.0/firebase-messaging.js';

const isSWSupported = () => 'serviceWorker' in navigator && 'Notification' in window;

async function loadESModule(url) {
    return await import(/* webpackIgnore: true */ url);
}

function getBrowserDeviceId() {
    const KEY = 'motcua_web_device_id';
    let id = localStorage.getItem(KEY);
    if (!id) {
        id = 'web-' + Math.random().toString(36).substring(2, 12) + '-' + Date.now();
        localStorage.setItem(KEY, id);
    }
    return id;
}

async function fetchFirebaseConfig() {
    try {
        const resp = await fetch(FCM_CONFIG_URL);
        const data = await resp.json();
        if (data.success && data.configured) {
            return data.config;
        }
        console.warn('[FCM Web] Firebase not configured in Odoo Settings.');
        return null;
    } catch (e) {
        console.error('[FCM Web] Cannot fetch Firebase config:', e);
        return null;
    }
}

async function registerTokenOnServer(fcmToken) {
    try {
        const userId = session.uid;
        const deviceId = getBrowserDeviceId();

        const resp = await fetch(FCM_REGISTER_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                fcm_token: fcmToken,
                device_id: deviceId,
                user_id: userId,
            }),
        });

        const data = await resp.json();
        if (data.success) {
            console.info('[FCM Web] Token registered:', data.data);
            localStorage.setItem('motcua_fcm_token', fcmToken);
        } else {
            console.warn('[FCM Web] Token registration failed:', data.message);
        }
        return data.success;
    } catch (e) {
        console.error('[FCM Web] Error registering token:', e);
        return false;
    }
}

// FIX: Use swReg.showNotification() instead of new Notification()
// Chrome 86+ blocks new Notification() from page context when SW is active
async function showForegroundNotification(payload, swReg) {
    const { title, body } = payload.notification || {};
    const data = payload.data || {};

    const notifTitle = title || 'Thong bao Mot Cua';
    const notifOptions = {
        body: body || '',
        icon: '/web/static/img/favicon.ico',
        badge: '/web/static/img/favicon.ico',
        tag: 'motcua-foreground-' + Date.now(),
        data: data,
        requireInteraction: false,
    };

    try {
        if (swReg && swReg.showNotification) {
            await swReg.showNotification(notifTitle, notifOptions);
        } else if (Notification.permission === 'granted') {
            new Notification(notifTitle, notifOptions);
        }
    } catch (e) {
        console.warn('[FCM Web] Cannot show notification:', e);
    }
}

async function initFcmWebPush() {
    if (!session.uid) return;

    if (!isSWSupported()) {
        console.info('[FCM Web] Browser does not support SW / Notification.');
        return;
    }

    const config = await fetchFirebaseConfig();
    if (!config) return;

    try {
        // FIX: Register SW at root path so FCM can receive background push
        const swReg = await navigator.serviceWorker.register(FCM_SW_URL, { scope: '/' });
        console.info('[FCM Web] Service Worker registered, scope:', swReg.scope);

        await navigator.serviceWorker.ready;

        // Send config to SW for background message handling
        const activeWorker = swReg.active || swReg.installing || swReg.waiting;
        if (activeWorker) {
            activeWorker.postMessage({ type: 'FIREBASE_CONFIG', config });
        }

        swReg.addEventListener('updatefound', () => {
            const newWorker = swReg.installing;
            if (newWorker) {
                newWorker.addEventListener('statechange', () => {
                    if (newWorker.state === 'activated') {
                        newWorker.postMessage({ type: 'FIREBASE_CONFIG', config });
                    }
                });
            }
        });

        const firebaseApp = await loadESModule(FIREBASE_JS_SDK);
        const firebaseMessaging = await loadESModule(FIREBASE_MESSAGING_SDK);

        const { initializeApp, getApps, getApp } = firebaseApp;
        const { getMessaging, getToken, onMessage } = firebaseMessaging;

        const app = getApps().length > 0 ? getApp() : initializeApp(config);
        const messaging = getMessaging(app);

        let permission = Notification.permission;
        if (permission === 'default') {
            permission = await Notification.requestPermission();
        }

        if (permission !== 'granted') {
            console.info('[FCM Web] Notification permission denied.');
            return;
        }

        const fcmToken = await getToken(messaging, {
            vapidKey: config.vapidKey,
            serviceWorkerRegistration: swReg,
        });

        if (!fcmToken) {
            console.warn('[FCM Web] Cannot get FCM token. Check VAPID key and SW scope.');
            return;
        }

        const savedToken = localStorage.getItem('motcua_fcm_token');
        if (savedToken !== fcmToken) {
            await registerTokenOnServer(fcmToken);
        } else {
            console.info('[FCM Web] Token unchanged, skip re-registration.');
        }

        onMessage(messaging, (payload) => {
            console.info('[FCM Web] Foreground message received:', payload);
            showForegroundNotification(payload, swReg);
        });

        navigator.serviceWorker.addEventListener('message', (event) => {
            if (event.data && event.data.type === 'NOTIFICATION_CLICK') {
                const notifyData = event.data.data || {};
                if (notifyData.type === 'request' && notifyData.id) {
                    window.location.href = `/web#action=service_request&id=${notifyData.id}`;
                }
            }
        });

        console.info('[FCM Web] Firebase Web Push initialized. Token:', fcmToken.substring(0, 20) + '...');

    } catch (e) {
        console.error('[FCM Web] Error initializing Firebase Web Push:', e);
    }
}

const fcmWebPushService = {
    start() {
        setTimeout(() => {
            initFcmWebPush().catch((e) => {
                console.error('[FCM Web] Unhandled error:', e);
            });
        }, 3000);
    },
};

registry.category('services').add('fcm_web_push', fcmWebPushService);
