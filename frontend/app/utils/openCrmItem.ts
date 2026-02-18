/**
 * Opens a CRM Smart Process item card in Bitrix24 slider.
 * 
 * @param entityTypeId - Smart Process entity type ID
 * @param itemId - Item ID (id_elem from normalized data)
 */
export function openCrmItemCard(entityTypeId: number | string, itemId: number | string) {
    const BX24 = (window as any).BX24
    const path = `/crm/type/${entityTypeId}/details/${itemId}/`

    if (typeof BX24 !== 'undefined') {
        BX24.openPath(path)
    } else {
        window.open(path, '_blank')
    }
}
