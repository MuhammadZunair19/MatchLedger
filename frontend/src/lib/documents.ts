export type Evidence = { original_value: string | null; normalized_value: string | null; page_number: number | null; bounding_box: number[] | null; confidence: number | null; extraction_method: string; uncertainty: string | null; verification_status: string };
export type ReviewLine = { id: string; description: string | null; quantity: string | null; unit_price: string | null; line_total: string | null; sku: string | null; unit_of_measure: string | null; purchase_order_line_id?: string | null };
export type ReviewData = { extraction_id: string; fields: Record<string, string | null>; lines: ReviewLine[]; supplier_id: string | null; purchase_order_id: string | null };
export type DocumentRow = { id: string; filename: string; document_type: string; status: string; created_at: string; size_bytes: number; page_count: number; last_error: string | null; supplier_name?: string | null; review_revision: number; review_data: ReviewData | null; business_entity_type: string | null; business_entity_id: string | null };
export type Extraction = { id: string; version: number; status: string; engine: string; created_at: string; completed_at: string | null; error: string | null; warnings: string[]; extracted_data: { fields: Record<string, Evidence>; lines: { id: string; fields: Record<string, Evidence>; uncertainty: string | null }[] } | null };
export type ExtractionResponse = { latest: Extraction | null; history: Extraction[]; review_data: ReviewData | null; review_revision: number; validation_warnings: string[] };
export const documentTypes: Record<string, string> = { purchase_order: 'Purchase order', supplier_invoice: 'Supplier invoice', goods_receipt: 'Delivery note' };
export const statuses = ['UPLOADED', 'QUEUED', 'PROCESSING', 'REVIEW_REQUIRED', 'VERIFIED', 'FAILED'];
export const pretty = (text: string) => text.replaceAll('_', ' ').toLowerCase().replace(/^./, c => c.toUpperCase());

export function uploadDocument(file: File, documentType: string, csrf: string, onProgress: (progress: number) => void): Promise<DocumentRow> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', '/api/documents/upload'); request.setRequestHeader('X-CSRF-Token', csrf);
    request.upload.onprogress = event => { if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100)); };
    request.onload = () => {
      let data; try { data = JSON.parse(request.responseText); } catch { reject(new Error('Upload failed: invalid server response')); return; }
      if (request.status >= 200 && request.status < 300) resolve(data);
      else reject(new Error(data.error?.message || 'Upload failed'));
    };
    request.onerror = () => reject(new Error('Network error while uploading'));
    const form = new FormData(); form.append('document_type', documentType); form.append('file', file); request.send(form);
  });
}
