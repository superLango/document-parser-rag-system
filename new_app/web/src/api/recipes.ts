import { apiRequest } from "./client";
import type { RecipeDetail, RecipeRef } from "./types";

export const recipesApi = {
  list: () => apiRequest<RecipeDetail[]>("/recipes"),
  get: (id: string) => apiRequest<RecipeDetail>(`/recipes/${id}`),
  rollback: (id: string, channel = "stable", note = "") =>
    apiRequest<RecipeRef>(`/recipes/${id}/rollback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel, actor: "local", note })
    })
};
