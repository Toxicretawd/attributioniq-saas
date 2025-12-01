// tracker.js
document.addEventListener('DOMContentLoaded', function() {
  // Get configuration from global window object
  const config = window.attributionIQ || {};
  const tenantId = config.tenant_id;
  const apiKey = config.api_key;
  
  if (!tenantId || !apiKey) {
    console.error('AttributionIQ: Missing tenant_id or api_key in configuration');
    return;
  }
  
  // Track initial page view
  trackEvent({
    customer_id: getCustomerId(),
    channel: getReferralChannel(),
    value: 1.0
  });
  
  // Expose conversion tracking function
  window.attributionIQ = window.attributionIQ || {};
  window.attributionIQ.trackConversion = function(value) {
    trackEvent({
      customer_id: getCustomerId(),
      channel: getReferralChannel(),
      value: 1.0,
      is_conversion: true,
      conversion_value: value || 0
    });
  };
  
  function trackEvent(data) {
    // Get the API endpoint from the config, or fall back to a relative URL
    const apiEndpoint = window.attributionIQ.api_endpoint || '';

    // Add the credentials to the data payload
    const payload = {
        ...data, // Includes customer_id, channel, etc.
        tenant_id: tenantId,
        api_key: apiKey
    };

    // Construct the full URL for the fetch request
    const fetchUrl = `${apiEndpoint}/api/v1/track`; // Make sure this line is correct

    fetch(fetchUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    })
    .catch(error => {
        console.error('AttributionIQ tracking error:', error);
    });
}
  
  function getReferralChannel() {
    const ref = document.referrer;
    if (!ref) return 'direct';
    
    const domains = {
      'google': 'google',
      'bing': 'bing',
      'yahoo': 'yahoo',
      'duckduckgo': 'duckduckgo',
      'facebook': 'facebook',
      'instagram': 'instagram',
      'twitter': 'twitter',
      'linkedin': 'linkedin',
      'tiktok': 'tiktok'
    };
    
    for (const [key, value] of Object.entries(domains)) {
      if (ref.includes(key)) return value;
    }
    
    return 'other';
  }
  
  function getCustomerId() {
    // Get or create customer ID (persists across sessions)
    let cid = localStorage.getItem('attributioniq_cid');
    if (!cid) {
      cid = Math.random().toString(36).substr(2, 10) + 
           Date.now().toString(36);
      localStorage.setItem('attributioniq_cid', cid);
    }
    return cid;
  }
});