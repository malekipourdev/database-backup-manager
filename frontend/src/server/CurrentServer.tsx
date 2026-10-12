import { type ReactNode, createContext, useCallback, useContext, useMemo, useState } from "react";

import { type Server, useServers } from "../api/servers";

const STORAGE_KEY = "mbp.server";

export interface CurrentServer {
  /** The selected server; null outside the panel's layout (e.g. in tests): all servers. */
  server: Server | null;
  /** Its id for the `server` parameter of the API; null means every server. */
  id: number | null;
  servers: Server[];
  select: (id: number) => void;
  /** False until the servers are loaded (pages wait for it); `error` if they could not be. */
  ready: boolean;
  error: unknown;
}

export const CurrentServerContext = createContext<CurrentServer>({
  server: null,
  id: null,
  servers: [],
  select: () => undefined,
  ready: true,
  error: null,
});

/** The server the panel is working on: databases, backups, schedules, containers, projects. */
export function useCurrentServer(): CurrentServer {
  return useContext(CurrentServerContext);
}

function readStored(): number | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw && /^\d+$/.test(raw) ? Number(raw) : null;
  } catch {
    return null; // storage can be unavailable; the panel's own server is then used
  }
}

function store(id: number): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(id));
  } catch {
    // Remembering the choice is a convenience only.
  }
}

/** The usable server for a stored choice: that one if it is connected, else the local one. */
export function pickServer(servers: Server[], wanted: number | null): Server | null {
  const chosen = servers.find((s) => s.id === wanted && s.paired);
  return chosen ?? servers.find((s) => s.kind === "local") ?? servers[0] ?? null;
}

export function CurrentServerProvider({ children }: { children: ReactNode }) {
  const servers = useServers();
  const [wanted, setWanted] = useState<number | null>(readStored);

  const select = useCallback((id: number) => {
    store(id);
    setWanted(id);
  }, []);

  const value = useMemo<CurrentServer>(() => {
    const list = servers.data ?? [];
    const server = servers.data ? pickServer(list, wanted) : null;
    return {
      server,
      id: server?.id ?? null,
      servers: list,
      select,
      ready: Boolean(servers.data),
      error: servers.data ? null : servers.error,
    };
  }, [servers.data, servers.error, wanted, select]);

  return <CurrentServerContext.Provider value={value}>{children}</CurrentServerContext.Provider>;
}
