import React from 'react';
import { createRoot } from 'react-dom/client';
import { DirectionProvider, MantineProvider } from '@mantine/core';
import '@mantine/core/styles.css';
import App from './App';
import './global.css';

const nonce = document.querySelector<HTMLMetaElement>('meta[name="style-nonce"]')?.content;
createRoot(document.getElementById('root')!).render(
  <React.StrictMode><DirectionProvider initialDirection={new URLSearchParams(location.search).get('locale') === 'fa-IR' ? 'rtl' : 'ltr'}>
    <MantineProvider forceColorScheme="light" withCssVariables={false} withGlobalClasses={false}
      getStyleNonce={() => nonce ?? ''}>
      <App />
    </MantineProvider>
  </DirectionProvider></React.StrictMode>,
);
