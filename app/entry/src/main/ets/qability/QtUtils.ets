/*
 * Module factories handed to Qt's internal JS state.
 *
 * Qt resolves service modules inside its own VM through this table; without a
 * "LocalStorage" entry the plugin's loadContent() call fails with
 * "global expression doesn't start with known module path:
 *  'LocalStorage.makeNewLocalStorage()'". The entry mirrors Qt's own ArkTS template
 * (qtbase/src/harmonyos/templates/entry/src/main/ets/qability/QtUtils.ets).
 *
 * ArkTS rejects indexed signatures, index access and some standard-library helpers, so
 * the table is a declared class whose own property is the module name.
 */
import { getLocalStorageTsInterface } from './LocalStorageTsModule';

// Empty table on purpose: the rebuilt plugin then takes the LocalStorage instance that
// QAbilityStage passes as "localStorage", which avoids the ETS factory round-trip.
class ModulesFactoriesTable {
}

export function getModulesFactoriesMapForQt(): object {
  return new ModulesFactoriesTable();
}

export default class QtUtils {
  static getModulesFactoriesMapForQt(): object {
    return getModulesFactoriesMapForQt();
  }
}
