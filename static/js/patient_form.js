(function (window, document) {
    'use strict';

    function resolvePatientType(baseType, trackValue) {
        if (trackValue === 'group') {
            return 'group';
        }
        if (trackValue === 'initial-intake') {
            return 'initial-intake';
        }
        if (trackValue === 'diagnosee') {
            return 'diagnosee';
        }
        return baseType || 'private';
    }

    function initPatientTypeSync(config) {
        var cfg = config || {};
        var statusInput = document.getElementById(cfg.statusId || 'status');
        var hiddenType = document.getElementById(cfg.hiddenTypeId || 'patientTypeHidden');
        var trackInput = document.getElementById(cfg.trackId || 'treatmentTrack');
        var baseInputs = document.querySelectorAll(cfg.baseSelector || 'input[name="patient_type_base"]');
        var forceCandidate = cfg.forceCandidate !== false;
        var onTrackChange = typeof cfg.onTrackChange === 'function' ? cfg.onTrackChange : null;

        if (!hiddenType || !trackInput || !baseInputs.length) {
            return null;
        }

        var syncPatientType = function () {
            var selectedBase = document.querySelector(cfg.baseSelector || 'input[name="patient_type_base"]:checked');
            var baseType = selectedBase ? selectedBase.value : 'private';
            var track = trackInput.value;
            hiddenType.value = resolvePatientType(baseType, track);

            if (forceCandidate && statusInput && track !== 'standard') {
                statusInput.value = 'candidate';
            }

            if (onTrackChange) {
                onTrackChange(track, hiddenType.value);
            }
        };

        baseInputs.forEach(function (input) {
            input.addEventListener('change', syncPatientType);
        });
        trackInput.addEventListener('change', syncPatientType);

        syncPatientType();

        return {
            sync: syncPatientType,
            resolvePatientType: resolvePatientType
        };
    }

    window.initPatientTypeSync = initPatientTypeSync;
})(window, document);
