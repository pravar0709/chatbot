import React from 'react';
import Chat from './components/Chat';
import ErrorBoundary from './components/ErrorBoundary';
import './App.css';

function App() {
  return (
    <ErrorBoundary>
      <div className="app">
        <header className="app-header">
          <div className="logo">
            <span className="logo-icon">⚡</span>
            <h1>Lyftr Chat</h1>
          </div>
          <span className="subtitle">LLM Chatbot with Key Failover & Caching</span>
        </header>
        <Chat />
      </div>
    </ErrorBoundary>
  );
}

export default App;
