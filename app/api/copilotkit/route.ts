import {
  CopilotRuntime,
  OpenAIAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { createOpenAI } from "@ai-sdk/openai";
import { tavily } from "@tavily/core";
import type { LanguageModel } from "ai";
import { NextRequest } from "next/server";
import OpenAI from "openai";

function createAzureFetch(apiVersion: string): typeof fetch {
  return async (input, init) => {
    const url = new URL(
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url,
    );
    if (!url.searchParams.has("api-version")) {
      url.searchParams.set("api-version", apiVersion);
    }
    return fetch(url, init);
  };
}

function createAzureOpenAIClient() {
  const apiKey = process.env.AZURE_API_KEY;
  const azureBase = process.env.AZURE_API_BASE?.replace(/\/$/, "");
  const deployment = process.env.AZURE_DEPLOYMENT_NAME ?? "gpt-4o";
  const apiVersion =
    process.env.AZURE_API_VERSION ?? "2024-08-01-preview";

  if (apiKey && azureBase) {
    return new OpenAI({
      apiKey,
      baseURL: `${azureBase}/openai/deployments/${deployment}`,
      defaultQuery: { "api-version": apiVersion },
      defaultHeaders: { "api-key": apiKey },
    });
  }

  return new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
}

function createAzureChatLanguageModel(): LanguageModel {
  const apiKey = process.env.AZURE_API_KEY!;
  const azureBase = process.env.AZURE_API_BASE!.replace(/\/$/, "");
  const deployment = process.env.AZURE_DEPLOYMENT_NAME ?? "gpt-4o";
  const apiVersion =
    process.env.AZURE_API_VERSION ?? "2024-08-01-preview";

  const provider = createOpenAI({
    apiKey,
    baseURL: `${azureBase}/openai/deployments/${deployment}`,
    headers: { "api-key": apiKey },
    fetch: createAzureFetch(apiVersion),
  });

  // Azure OpenAI does not support the Responses API; use Chat Completions.
  return provider.chat(deployment);
}

const deployment = process.env.AZURE_DEPLOYMENT_NAME ?? "gpt-4o";
const openai = createAzureOpenAIClient();
const serviceAdapter = new OpenAIAdapter({
  openai,
  model: deployment,
});

if (process.env.AZURE_API_KEY && process.env.AZURE_API_BASE) {
  serviceAdapter.getLanguageModel = () => createAzureChatLanguageModel();
}

const runtime = new CopilotRuntime({
  actions: () => [
    {
      name: "searchInternet",
      description: "Searches the internet for information.",
      parameters: [
        {
          name: "query",
          type: "string",
          description: "The query to search the internet for.",
          required: true,
        },
      ],
      handler: async ({ query }: { query: string }) => {
        const tvly = tavily({ apiKey: process.env.TAVILY_API_KEY });
        return await tvly.search(query, { max_results: 5 });
      },
    },
  ],
});

export const POST = async (req: NextRequest) => {
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter,
    endpoint: "/api/copilotkit",
  });

  return handleRequest(req);
};
