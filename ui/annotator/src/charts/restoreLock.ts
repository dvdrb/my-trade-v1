/** KLineChart's lock flag is inverted from the workstation's interactive state. */
export const restoreOverlayLock = (interactive: boolean): boolean => !interactive;
