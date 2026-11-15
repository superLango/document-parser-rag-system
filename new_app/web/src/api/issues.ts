import { apiRequest } from "./client";
import type { IssueLedger } from "./types";

export const issuesApi = {
  ledger: () => apiRequest<IssueLedger>("/issues/ledger")
};
