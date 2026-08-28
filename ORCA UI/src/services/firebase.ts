import { initializeApp, getApps, getApp } from 'firebase/app';
import { getAnalytics, isSupported } from 'firebase/analytics';
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
  onAuthStateChanged,
  User,
} from 'firebase/auth';
import {
  getFirestore,
  doc,
  setDoc,
  getDocs,
  deleteDoc,
  collection,
  query,
  orderBy,
} from 'firebase/firestore';
import { Chat } from '../types/chat';
import { Message } from '../types/message';

export const firebaseConfig = {
  apiKey: "AIzaSyACNEnzNQkQvdHD-6AqnABfHYF-gnFXQeE",
  authDomain: "orca-2530.firebaseapp.com",
  projectId: "orca-2530",
  storageBucket: "orca-2530.firebasestorage.app",
  messagingSenderId: "365278441289",
  appId: "1:365278441289:web:b62eba8e5af6fdb0187498",
  measurementId: "G-56MZ74JRKV"
};

// Initialize Firebase App singleton
export const firebaseApp = getApps().length === 0 ? initializeApp(firebaseConfig) : getApp();

// Initialize Firebase Authentication
export const auth = getAuth(firebaseApp);
export const googleProvider = new GoogleAuthProvider();
googleProvider.setCustomParameters({ prompt: 'select_account' });

// Initialize Cloud Firestore
export const db = getFirestore(firebaseApp);

export async function loginWithGooglePopup(): Promise<User> {
  const result = await signInWithPopup(auth, googleProvider);
  return result.user;
}

export async function logoutUser(): Promise<void> {
  await signOut(auth);
}

export function subscribeToAuth(callback: (user: User | null) => void): () => void {
  return onAuthStateChanged(auth, callback);
}

/**
 * Save user profile info and update last active timestamp in Firestore
 */
export async function saveUserProfile(user: User): Promise<void> {
  try {
    const userRef = doc(db, 'users', user.uid);
    await setDoc(userRef, {
      uid: user.uid,
      displayName: user.displayName || 'Watch Officer',
      email: user.email,
      photoURL: user.photoURL || null,
      lastActiveAt: Date.now(),
    }, { merge: true });
  } catch (err) {
    console.warn('[Firestore] Failed to save user profile:', err);
  }
}

/**
 * Save or update a mission brief / chat session in Firestore (Only for authenticated users)
 */
export async function saveUserChatToFirestore(uid: string, chat: Chat): Promise<void> {
  if (!uid || !chat || !chat.id) return;
  try {
    const chatRef = doc(db, 'users', uid, 'chats', chat.id);
    await setDoc(chatRef, {
      id: chat.id,
      title: chat.title || 'Marine Briefing',
      createdAt: chat.createdAt || Date.now(),
      updatedAt: chat.updatedAt || Date.now(),
      agentId: chat.agentId || 'orca-nav',
      model: chat.model || 'llama-3.3-70b-versatile',
      pinned: chat.pinned || false,
      project: chat.project || 'General',
      tags: chat.tags || [],
      messageCount: chat.messageCount || 0,
      lastMessagePreview: chat.lastMessagePreview || '',
    }, { merge: true });
    console.info(`[Firestore] Chat ${chat.id} saved for user ${uid}`);
  } catch (err) {
    console.warn('[Firestore] Failed to save chat session:', err);
  }
}

/**
 * Delete a mission brief / chat session and its subcollection from Firestore
 */
export async function deleteUserChatFromFirestore(uid: string, chatId: string): Promise<void> {
  if (!uid || !chatId) return;
  try {
    const chatRef = doc(db, 'users', uid, 'chats', chatId);
    await deleteDoc(chatRef);
    console.info(`[Firestore] Chat ${chatId} deleted for user ${uid}`);
  } catch (err) {
    console.warn('[Firestore] Failed to delete chat:', err);
  }
}

/**
 * Save a message (user prompt or AI advisory with activity trace) in Firestore
 */
export async function saveUserMessageToFirestore(uid: string, chatId: string, message: Message): Promise<void> {
  if (!uid || !chatId || !message || !message.id) return;
  try {
    const msgRef = doc(db, 'users', uid, 'chats', chatId, 'messages', message.id);
    // Sanitize undefined fields for Firestore
    const payload: Record<string, any> = {
      id: message.id,
      chatId: message.chatId || chatId,
      role: message.role,
      content: message.content || '',
      timestamp: message.timestamp || Date.now(),
    };
    if (message.agentId) payload.agentId = message.agentId;
    if (message.modelUsed) payload.modelUsed = message.modelUsed;
    if (message.isEdited !== undefined) payload.isEdited = message.isEdited;
    if (message.reactions) payload.reactions = message.reactions;
    if (message.tokens) payload.tokens = message.tokens;
    if (message.attachments && message.attachments.length > 0) payload.attachments = message.attachments;
    if (message.activitySteps && message.activitySteps.length > 0) payload.activitySteps = message.activitySteps;

    await setDoc(msgRef, payload, { merge: true });
  } catch (err) {
    console.warn('[Firestore] Failed to save message:', err);
  }
}

/**
 * Retrieve all user chats and their messages from Firestore
 */
export async function loadUserSessionsFromFirestore(uid: string): Promise<{
  chats: Chat[];
  messages: Record<string, Message[]>;
} | null> {
  try {
    const chatsRef = collection(db, 'users', uid, 'chats');
    const q = query(chatsRef, orderBy('updatedAt', 'desc'));
    const snapshot = await getDocs(q);

    if (snapshot.empty) {
      return null;
    }

    const chats: Chat[] = [];
    const messages: Record<string, Message[]> = {};

    for (const chatDoc of snapshot.docs) {
      const chatData = chatDoc.data() as Chat;
      chats.push(chatData);

      // Load messages for this chat
      const msgsRef = collection(db, 'users', uid, 'chats', chatData.id, 'messages');
      const msgsQuery = query(msgsRef, orderBy('timestamp', 'asc'));
      const msgsSnap = await getDocs(msgsQuery);

      messages[chatData.id] = msgsSnap.docs.map(doc => doc.data() as Message);
    }

    return { chats, messages };
  } catch (err) {
    console.warn('[Firestore] Failed to load user sessions:', err);
    return null;
  }
}

// Initialize Analytics safely
export let analytics: ReturnType<typeof getAnalytics> | null = null;
if (typeof window !== 'undefined') {
  isSupported().then((supported) => {
    if (supported) {
      analytics = getAnalytics(firebaseApp);
    }
  }).catch((err) => {
    console.warn('Firebase analytics initialization skipped:', err);
  });
}
