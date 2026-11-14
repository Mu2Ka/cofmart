import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  workers: 2,
  timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:4177', channel: 'msedge', headless: true,
         viewport: {width:390,height:844}, screenshot:'only-on-failure', trace:'retain-on-failure' },
  webServer: {
    command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4177 --strictPort',
    url: 'http://127.0.0.1:4177', reuseExistingServer: false,
    env: {...process.env, VITE_API_URL:'/api'},
  },
});
