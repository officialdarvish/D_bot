'use client';

import { createContext, useContext } from 'react';
import catalog from './miniapp-copy-catalog.json';

export type CopyKey = keyof typeof catalog;
export type CopyOverrides = Partial<Record<CopyKey, string>>;
type Variables = Record<string, string | number>;
export type MiniAppCopy = (key: CopyKey, variables?: Variables, fallback?: string) => string;

export const miniAppCopyCatalog = catalog;
const empty: CopyOverrides = {};
export const MiniAppCopyContext = createContext<CopyOverrides>(empty);

export function miniAppText(overrides: CopyOverrides | undefined, key: CopyKey, variables?: Variables, fallback?: string) {
  const template = overrides?.[key] || fallback || catalog[key].text;
  return variables ? template.replace(/\{([A-Za-z][A-Za-z0-9_]*)\}/g, (token, name: string) =>
    Object.prototype.hasOwnProperty.call(variables, name) ? String(variables[name]) : token
  ) : template;
}

export function useMiniAppCopy(): MiniAppCopy {
  const overrides = useContext(MiniAppCopyContext);
  return (key, variables, fallback) => miniAppText(overrides, key, variables, fallback);
}
