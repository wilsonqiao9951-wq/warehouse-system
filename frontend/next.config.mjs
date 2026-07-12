import path from "node:path";
import { fileURLToPath } from "node:url";

/** @type {import('next').NextConfig} */
/**
 * `output: "export"` 与 `next dev` 同时使用在部分环境下会导致 webpack chunk 丢失
 *（例如 Cannot find module './24.js'）。开发模式关闭静态导出，仅在生产 build 时启用。
 */
const isProd = process.env.NODE_ENV === "production";
const projectRoot = path.dirname(fileURLToPath(import.meta.url));

const nextConfig = {
  reactStrictMode: true,
  trailingSlash: true,
  turbopack: { root: projectRoot },
  ...(isProd ? { output: "export" } : {})
};

export default nextConfig;
