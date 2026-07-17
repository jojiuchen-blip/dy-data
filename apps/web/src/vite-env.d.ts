/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DEMO_MODE?: string;
}

declare module "*.csv?raw" {
  const content: string;
  export default content;
}
