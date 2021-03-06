/*global FormplayerFrontend */

FormplayerFrontend.module("SessionNavigate", function (SessionNavigate, FormplayerFrontend, Backbone, Marionette) {
    SessionNavigate.Middleware = {
        apply: function(api) {
            var wrappedApi = {};
            _.each(api, function(value, key) {
                wrappedApi[key] = function() {
                    _.each(SessionNavigate.Middleware.middlewares, function(fn) {
                        fn.call(null, key);
                    });
                    return value.apply(null, arguments);
                };
            });
            return wrappedApi;
        },
    };
    var backButtonShowHideMiddleware = function(name) {
        if (name === 'singleApp') {
            FormplayerFrontend.trigger('phone:back:hide');
        } else {
            FormplayerFrontend.trigger('phone:back:show');
        }
    };
    var logRouteMiddleware = function(name) {
        window.console.log('User navigated to ' + name);
    };
    var clearFormMiddleware = function(name) {
        FormplayerFrontend.trigger("clearForm");
    };

    SessionNavigate.Middleware.middlewares = [
        logRouteMiddleware,
        backButtonShowHideMiddleware,
        clearFormMiddleware,
    ];
});
