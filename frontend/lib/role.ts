export type AppRole = "engineer" | "manager" | "warehouse" | "admin";

export function getCurrentRole(): AppRole {
  if (typeof window === "undefined") return "admin";
  const saved = window.localStorage.getItem("opf_role");
  if (saved === "engineer" || saved === "manager" || saved === "warehouse" || saved === "admin") {
    return saved;
  }
  return "admin";
}
