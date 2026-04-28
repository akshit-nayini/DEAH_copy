import { requirementsModule } from "./requirements";
import { designModule } from "./design";
import { developmentModule } from "./development";
import { testingModule } from "./testing";
import { knowledgeBuildModule } from "./knowledgeBuild";

export const MODULES = [
  requirementsModule,
  designModule,
  developmentModule,
  testingModule,
  knowledgeBuildModule,
];

export type Module = typeof MODULES[number];
export type SubModule = Module["subModules"][number];
