"use client";

import { ClerkProvider } from "@clerk/clerk-react";
import type { ReactNode } from "react";

const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export default function ClientProviders({ children }: { children: ReactNode }) {
  if (!publishableKey) {
    throw new Error(
      "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is required to initialize Clerk."
    );
  }
  return <ClerkProvider publishableKey={publishableKey}>{children}</ClerkProvider>;
}
