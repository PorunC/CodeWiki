export type FrontendNpmCommand =
  | {
      ok: true;
      frontendDir: string;
      command: string;
      args: string[];
    }
  | {
      ok: false;
      frontendDir: string;
      message: string;
    };

export declare function frontendNpmCommand(
  argv: string[],
  env?: Record<string, string | undefined>
): FrontendNpmCommand;

export declare function resolveFromRoot(value: string): string;

export declare function isWsl(): boolean;

export declare function isWindowsToolOnWsl(path: string): boolean;
