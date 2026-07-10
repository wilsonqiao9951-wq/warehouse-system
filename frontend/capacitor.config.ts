import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.openpartsflow.app",
  appName: "OpenPartsFlow",
  webDir: "out",
  server: {
    androidScheme: "https"
  }
};

export default config;
